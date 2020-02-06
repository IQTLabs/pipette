#!/usr/bin/python3

# pipette implements a simple TCP-only L2/L3 proxy between a
# real broadcast domain/subnet and a fake one.

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

import ipaddress
import socket
import os
import netaddr
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ether
from ryu.ofproto import nicira_ext
from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as parser


# OVS port facing coprocessor (expects packets with or without a tag from the configured VLAN)
# Coprocessor only accepts packets with a VLAN tag.
# TODO: add flows to handle packets from VLAN ACL with tag as well.
COPROPORT = int(os.getenv('COPROPORT', '1'))
# OVS port facing fake services.
FAKEPORT = int(os.getenv('FAKEPORT', '2'))
# Fake interface must have this MAC.
FAKESERVERMAC = netaddr.EUI(os.getenv('FAKESERVERMAC', '0e:00:00:00:00:66'), dialect=netaddr.mac_unix)
# We will fake all coprocessed hosts as having this MAC.
FAKECLIENTMAC = netaddr.EUI(os.getenv('FAKECLIENTMAC', '0e:00:00:00:00:67'), dialect=netaddr.mac_unix)
# VLAN to coprocess
VLAN = int(os.getenv('VLAN', '2'))
# IP address of fake services.
# TODO: add IPv6 support
NFVIP = ipaddress.ip_interface(os.getenv('NFVIP', '10.10.0.1/16'))
# Idle timeout for translated flows (garbage collect)
IDLE = 300


class Pipette(app_manager.RyuApp):

    OFP_VERSIONS = [ofp.OFP_VERSION]

    def send_mods(self, datapath, mods):
        for mod in mods:
            datapath.send_msg(mod)


    @staticmethod
    def apply_actions(actions):
        return [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]


    def nat_flows(self):
        # configure automatic learning.
        nat_base = NFVIP.network.network_address
        # pylint: disable=no-member
        return self.apply_actions([
            # first, calculate src NAT address, leave in reg0.
            parser.NXActionRegMove(src_field='ipv4_src', dst_field='reg0', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.NXActionRegLoad(value=((int(nat_base) & 0xffff0000) >> 16), dst='reg0', ofs_nbits=nicira_ext.ofs_nbits(16, 31)),
            parser.NXActionRegMove(src_field='reg0', dst_field='reg0', n_bits=8, src_ofs=0, dst_ofs=8),
            parser.NXActionRegMove(src_field='ipv4_dst', dst_field='reg0', n_bits=8, src_ofs=0, dst_ofs=0),
            # we have to load output port numbers into reg1 and reg2 because NXFlowSpecOutput() won't take a literal.
            parser.NXActionRegLoad(value=FAKEPORT, dst='reg1', ofs_nbits=nicira_ext.ofs_nbits(0, 2)),
            parser.NXActionRegLoad(value=COPROPORT, dst='reg2', ofs_nbits=nicira_ext.ofs_nbits(0, 2)),
            # now program an inbound flow to perform NAT.
            parser.NXActionLearn(
                table_id=1,
                priority=2,
                hard_timeout=IDLE,
                specs=[
                    parser.NXFlowSpecMatch(src=ether.ETH_TYPE_IP, dst=('eth_type_nxm', 0), n_bits=16),
                    parser.NXFlowSpecMatch(src=('ipv4_src_nxm', 0), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecMatch(src=('ipv4_dst_nxm', 0), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=('reg0', 0), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=int(NFVIP.ip), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=int(FAKECLIENTMAC), dst=('eth_src_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=int(FAKESERVERMAC), dst=('eth_dst_nxm', 0), n_bits=48),
                    parser.NXFlowSpecOutput(src=('reg1', 0), dst='', n_bits=2),
                ]),
            # now program outbound an outbound flow.
            parser.NXActionLearn(
                table_id=2,
                priority=2,
                idle_timeout=IDLE,
                specs=[
                    parser.NXFlowSpecMatch(src=ether.ETH_TYPE_IP, dst=('eth_type_nxm', 0), n_bits=16),
                    parser.NXFlowSpecMatch(src=int(NFVIP.ip), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecMatch(src=('reg0', 0), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=('eth_src_nxm', 0), dst=('eth_dst_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=('eth_dst_nxm', 0), dst=('eth_src_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=('ipv4_src_nxm', 0), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=('ipv4_dst_nxm', 0), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecOutput(src=('reg2', 0), dst='', n_bits=2),
                ]),
            # now that future flows are programmed, handle the packet we have.
            parser.OFPActionSetField(eth_src=str(FAKECLIENTMAC)),
            parser.OFPActionSetField(eth_dst=str(FAKESERVERMAC)),
            parser.NXActionRegMove(src_field='reg0', dst_field='ipv4_src', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.OFPActionSetField(ipv4_dst=str(NFVIP.ip)),
            parser.OFPActionOutput(FAKEPORT)])


    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)  # pylint: disable=no-member
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
        copro_out_actions = self.apply_actions([
            parser.OFPActionPushVlan(ether.ETH_TYPE_8021Q),
            parser.OFPActionSetField(vlan_vid=(VLAN | ofp.OFPVID_PRESENT))])
        # OVS could then add the proxy entries itself rather than pipette.
        for table_id, match, instructions in (
                # Learn from coprocessor port/do inbound translation.
                (1, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_TCP),
                 self.nat_flows()),
                (1, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_UDP),
                 self.nat_flows()),
                # Program OVS to respond to ARP on fake port.
                (2, parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP, arp_op=0x1),
                 # pylint: disable=no-member
                 self.apply_actions([
                     parser.NXActionRegMove(src_field='arp_tpa', dst_field='reg0', n_bits=32, src_ofs=0, dst_ofs=0),
                     parser.NXActionRegLoad(value=0x2, dst='arp_op', ofs_nbits=nicira_ext.ofs_nbits(0, 2)),
                     parser.NXActionRegMove(src_field='eth_src', dst_field='eth_dst', n_bits=48, src_ofs=0, dst_ofs=0),
                     parser.NXActionRegMove(src_field='arp_sha', dst_field='arp_tha', n_bits=48, src_ofs=0, dst_ofs=0),
                     parser.NXActionRegMove(src_field='arp_spa', dst_field='arp_tpa', n_bits=32, src_ofs=0, dst_ofs=0),
                     parser.NXActionRegMove(src_field='reg0', dst_field='arp_spa', n_bits=32, src_ofs=0, dst_ofs=0),
                     parser.OFPActionSetField(eth_src=str(FAKECLIENTMAC)),
                     parser.OFPActionSetField(arp_sha=str(FAKECLIENTMAC)),
                     parser.OFPActionOutput(ofp.OFPP_IN_PORT),
                 ])),
                # If coprocessor gives us a tagged packet, strip it.
                (0, parser.OFPMatch(vlan_vid=(0x1000, 0x1000), in_port=COPROPORT),
                 self.apply_actions([parser.OFPActionPopVlan()]) + [parser.OFPInstructionGotoTable(1)]),
                # Packets from coprocessor go to tuple inbound table.
                (0, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_TCP, in_port=COPROPORT),
                 [parser.OFPInstructionGotoTable(1)]),
                (0, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_UDP, in_port=COPROPORT),
                 [parser.OFPInstructionGotoTable(1)]),
                # Packets from fake interface go outbound table.
                (0, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_TCP, in_port=FAKEPORT),
                 copro_out_actions + [parser.OFPInstructionGotoTable(2)]),
                (0, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_UDP, in_port=FAKEPORT),
                 copro_out_actions + [parser.OFPInstructionGotoTable(2)]),
                (0, parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP, eth_src=FAKESERVERMAC, in_port=FAKEPORT),
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
