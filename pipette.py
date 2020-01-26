#!/usr/bin/python3

# pipette implements a simple TCP-only L2/L3 proxy between a real broadcast domain/subnet and a fake one.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import socket
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ether
from ryu.lib.packet import ethernet, ipv4, packet, arp, tcp
from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as parser


# OVS port facing coprocessor (expects packets without a VLAN tag from a FAUCET port ACL)
# Coprocessor only accepts packets with a VLAN tag.
# TODO: add flows to handle packets from VLAN ACL with tag as well.
COPROPORT = 1
# OVS port facing fake services.
FAKEPORT = 2
# Fake interface must have this MAC.
FAKESERVERMAC = '0e:00:00:00:00:66'
# We will fake all coprocessed hosts as having this MAC.
FAKECLIENTMAC = '0e:00:00:00:00:67'
# VLAN to coprocess
VLAN = 2
# IP address of fake services.
NFVIP = '192.168.2.1'
# Idle timeout for translated flows (garbage collect)
IDLE = 30


class Pipette(app_manager.RyuApp):

    OFP_VERSIONS = [ofp.OFP_VERSION]

    def send_mods(self, datapath, mods):
        for mod in mods:
            datapath.send_msg(mod)

    def apply_actions(self, actions):
        return [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]

    def output_controller(self):
        return self.apply_actions([parser.OFPActionOutput(ofp.OFPP_CONTROLLER)])

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        mods = []
        # Drop all flows.
        mods.append(parser.OFPFlowMod(
            datapath=datapath,
            command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
        ))
        # Default deny all tables
        for table_id in (0, 1, 2):
            mods.append(parser.OFPFlowMod(
                datapath=datapath,
                command=ofp.OFPFC_ADD,
                table_id=table_id,
                priority=0,
                instructions=[]))
        for table_id, match, instructions in (
                # Learn TCP 3-tuple from coprocessor port/do inbound translation.
                # TODO: use 4-tuple with source port as well.
                (1, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_TCP),
                 self.output_controller()),
                # Do outbound translation and also handle fake ARP to services on fake interface.
                (2, parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP),
                 self.output_controller()),
                # Packets from coprocessor go to TCP-3 tuple inbound table.
                (0, parser.OFPMatch(in_port=COPROPORT),
                 [parser.OFPInstructionGotoTable(1)]),
                # Packets from fake interface go to TCP-3'd outbound table.
                (0, parser.OFPMatch(in_port=FAKEPORT),
                 [parser.OFPInstructionGotoTable(2)]),
            ):
            mods.append(parser.OFPFlowMod(
                datapath=datapath,
                command=ofp.OFPFC_ADD,
                table_id=table_id,
                priority=1,
                match=match,
                instructions=instructions))
        self.send_mods(datapath, mods)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        mods = []
        if in_port == FAKEPORT:
            arp_req = pkt.get_protocol(arp.arp)
            if not arp_req:
                return
            opcode = arp_req.opcode
            # Reply to fake service, proxying real host.
            if opcode == arp.ARP_REQUEST:
                pkt = packet.Packet()
                eth_header = ethernet.ethernet(FAKESERVERMAC, FAKECLIENTMAC, ether.ETH_TYPE_ARP)
                pkt.add_protocol(eth_header)
                arp_pkt = arp.arp(
                    opcode=arp.ARP_REPLY,
                    src_mac=FAKECLIENTMAC, dst_mac=FAKESERVERMAC,
                    src_ip=arp_req.dst_ip, dst_ip=arp_req.src_ip)
                pkt.add_protocol(arp_pkt)
                pkt.serialize()
                mod = parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=ofp.OFP_NO_BUFFER,
                    in_port=ofp.OFPP_CONTROLLER,
                    actions=[parser.OFPActionOutput(FAKEPORT)],
                    data=pkt.data)
                mods.append(mod)
        if in_port == COPROPORT:
            ip4 = pkt.get_protocol(ipv4.ipv4)
            if not ip4:
                return
            tcp4 = pkt.get_protocol(tcp.tcp)
            if not tcp4:
                return
            priority = 2
            # Add inbound from coprocessor translation entry.
            match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP, eth_src=eth.src,
                ipv4_dst=ip4.dst, ip_proto=socket.IPPROTO_TCP, tcp_dst=tcp4.dst_port)
            actions = [
                parser.OFPActionSetField(eth_src=FAKECLIENTMAC),
                parser.OFPActionSetField(eth_dst=FAKESERVERMAC),
                parser.OFPActionSetField(ipv4_dst=NFVIP),
                parser.OFPActionOutput(FAKEPORT)]
            mods.append(parser.OFPFlowMod(
                datapath=datapath,
                command=ofp.OFPFC_ADD,
                table_id=1,
                priority=priority,
                match=match,
                idle_timeout=IDLE,
                instructions=self.apply_actions(actions)))
            # Add outbound to coprocessor translation entry.
            match = parser.OFPMatch(
                eth_type=ether.ETH_TYPE_IP,
                ipv4_dst=ip4.src, ip_proto=socket.IPPROTO_TCP, tcp_src=tcp4.dst_port)
            actions = [
                parser.OFPActionSetField(eth_src=eth.dst),
                parser.OFPActionSetField(eth_dst=eth.src),
                parser.OFPActionSetField(ipv4_src=ip4.dst),
                parser.OFPActionPushVlan(ether.ETH_TYPE_8021Q),
                parser.OFPActionSetField(vlan_vid=(VLAN | ofp.OFPVID_PRESENT)),
                parser.OFPActionOutput(COPROPORT)]
            mods.append(parser.OFPFlowMod(
                datapath=datapath,
                command=ofp.OFPFC_ADD,
                table_id=2,
                priority=priority,
                match=match,
                idle_timeout=IDLE,
                instructions=self.apply_actions(actions)))
        self.send_mods(datapath, mods)
