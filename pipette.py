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
from ryu.controller.handler import CONFIG_DISPATCHER, set_ev_cls
from ryu.lib.packet import arp
from ryu.ofproto import ether, nicira_ext
from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as parser


# OVS port facing coprocessor (expects packets with a tag from the configured VLAN/s)
# Coprocessor only accepts packets with a VLAN tag.
COPROPORT = int(os.getenv('COPROPORT', '1'))
# OVS port facing fake services.
FAKEPORT = int(os.getenv('FAKEPORT', '2'))
# Fake interface must have this MAC.
FAKESERVERMAC = netaddr.EUI(os.getenv('FAKESERVERMAC', '0e:00:00:00:00:66'), dialect=netaddr.mac_unix)
# We will fake all coprocessed hosts as having this MAC.
FAKECLIENTMAC = netaddr.EUI(os.getenv('FAKECLIENTMAC', '0e:00:00:00:00:67'), dialect=netaddr.mac_unix)
# VLAN(s) to coprocess
VLANS = [int(vlan) for vlan in os.getenv('VLANS', '2').split(' ')]
# IP addresses of fake services.
# TODO: add IPv6 support
NFVIPS = [ipaddress.ip_interface(nfvip) for nfvip in os.getenv('NFVIPS', '10.10.0.1/16').split(' ')]
# Idle timeout for translated flows (garbage collect)
IDLE = 300


INTF_TABLE = 0
FROM_COPRO_TABLE = 1
TO_COPRO_TABLE = 2


class Pipette(app_manager.RyuApp):

    OFP_VERSIONS = [ofp.OFP_VERSION]

    @staticmethod
    def send_mods(datapath, mods):
        for mod in mods:
            datapath.send_msg(mod)


    @staticmethod
    def apply_actions(actions):
        return [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]


    def nat_flows(self, nfvip):
        # configure automatic learning.
        nat_base = nfvip.network.network_address
        # pylint: disable=no-member
        return self.apply_actions([
            # first, calculate src NAT address, leave in reg0.
            # Assuming ipv4_src is 192.168.2.5, ipv4_dst is 192.168.2.1, and NFVIP is 10.10.0.1/24
            # ipv4_src becomes 10.10.5.1 (low octet of dst is LSB, then low octet of src).
            parser.NXActionRegLoad(value=int(nat_base), dst='reg0', ofs_nbits=nicira_ext.ofs_nbits(0, 31)),
            parser.NXActionRegMove(src_field='ipv4_src', dst_field='reg0', n_bits=8, src_ofs=0, dst_ofs=8),
            parser.NXActionRegMove(src_field='ipv4_dst', dst_field='reg0', n_bits=8, src_ofs=0, dst_ofs=0),
            # we have to load output port numbers into reg1 and reg2 because NXFlowSpecOutput() won't take a literal.
            parser.NXActionRegLoad(value=FAKEPORT, dst='reg1', ofs_nbits=nicira_ext.ofs_nbits(0, 15)),
            parser.NXActionRegLoad(value=COPROPORT, dst='reg2', ofs_nbits=nicira_ext.ofs_nbits(0, 15)),
            # now program an inbound flow to perform NAT.
            parser.NXActionLearn(
                table_id=FROM_COPRO_TABLE,
                priority=2,
                hard_timeout=IDLE,
                specs=[
                    parser.NXFlowSpecMatch(src=ether.ETH_TYPE_IP, dst=('eth_type_nxm', 0), n_bits=16),
                    parser.NXFlowSpecMatch(src=('ipv4_src_nxm', 0), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecMatch(src=('ipv4_dst_nxm', 0), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=int(FAKECLIENTMAC), dst=('eth_src_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=int(FAKESERVERMAC), dst=('eth_dst_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=('reg0', 0), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=int(nfvip.ip), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecOutput(src=('reg1', 0), dst='', n_bits=16),
                ]),
            # now program outbound an outbound flow.
            parser.NXActionLearn(
                table_id=TO_COPRO_TABLE,
                priority=2,
                idle_timeout=IDLE,
                specs=[
                    parser.NXFlowSpecMatch(src=ether.ETH_TYPE_IP, dst=('eth_type_nxm', 0), n_bits=16),
                    parser.NXFlowSpecMatch(src=int(nfvip.ip), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecMatch(src=('reg0', 0), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=('eth_dst_nxm', 0), dst=('eth_src_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=('eth_src_nxm', 0), dst=('eth_dst_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=('ipv4_dst_nxm', 0), dst=('ipv4_src_nxm', 0), n_bits=32),
                    parser.NXFlowSpecLoad(src=('ipv4_src_nxm', 0), dst=('ipv4_dst_nxm', 0), n_bits=32),
                    parser.NXFlowSpecOutput(src=('reg2', 0), dst='', n_bits=16),
                ]),
            # now that future flows are programmed, handle the packet we have.
            parser.OFPActionSetField(eth_src=FAKECLIENTMAC),
            parser.OFPActionSetField(eth_dst=FAKESERVERMAC),
            parser.NXActionRegMove(src_field='reg0', dst_field='ipv4_src', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.OFPActionSetField(ipv4_dst=str(nfvip.ip)),
            parser.OFPActionOutput(FAKEPORT)])


    def arp_reply_actions(self):
        # pylint: disable=no-member
        return self.apply_actions([
            parser.NXActionRegLoad(value=arp.ARP_REPLY, dst='arp_op', ofs_nbits=nicira_ext.ofs_nbits(0, 2)),
            parser.NXActionRegMove(src_field='eth_src', dst_field='eth_dst', n_bits=48, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='arp_sha', dst_field='arp_tha', n_bits=48, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='arp_tpa', dst_field='reg0', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='arp_spa', dst_field='arp_tpa', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='reg0', dst_field='arp_spa', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.OFPActionSetField(eth_src=FAKECLIENTMAC),
            parser.OFPActionSetField(arp_sha=FAKECLIENTMAC),
            parser.OFPActionOutput(ofp.OFPP_IN_PORT)])


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
        for table_id in (INTF_TABLE, FROM_COPRO_TABLE, TO_COPRO_TABLE):
            mods.append(parser.OFPFlowMod(
                datapath=datapath,
                command=ofp.OFPFC_ADD,
                table_id=table_id,
                priority=0,
                instructions=[]))
        for vlan, nfvip in zip(VLANS, NFVIPS):
            vlan_id = (vlan | ofp.OFPVID_PRESENT)
            for table_id, match, instructions in (
                    # Program OVS to respond to ARP on fake port.
                    (TO_COPRO_TABLE, parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP, vlan_vid=vlan_id),
                     self.arp_reply_actions()),
                    # Learn from coprocessor port/do inbound translation.
                    (FROM_COPRO_TABLE, parser.OFPMatch(eth_type=ether.ETH_TYPE_IP, vlan_vid=vlan_id),
                     self.nat_flows(nfvip)),
                    # Packets from coprocessor go to tuple inbound table.
                    (INTF_TABLE, parser.OFPMatch(
                        eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_TCP, in_port=COPROPORT, vlan_vid=vlan_id),
                     [parser.OFPInstructionGotoTable(FROM_COPRO_TABLE)]),
                    (INTF_TABLE, parser.OFPMatch(
                        eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_UDP, in_port=COPROPORT, vlan_vid=vlan_id),
                     [parser.OFPInstructionGotoTable(FROM_COPRO_TABLE)]),
                    # Packets from fake interface go outbound table.
                    (INTF_TABLE, parser.OFPMatch(
                        eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_TCP, in_port=FAKEPORT, vlan_vid=vlan_id),
                     [parser.OFPInstructionGotoTable(TO_COPRO_TABLE)]),
                    (INTF_TABLE, parser.OFPMatch(
                        eth_type=ether.ETH_TYPE_IP, ip_proto=socket.IPPROTO_UDP, in_port=FAKEPORT, vlan_vid=vlan_id),
                     [parser.OFPInstructionGotoTable(TO_COPRO_TABLE)]),
                    (INTF_TABLE, parser.OFPMatch(
                        eth_type=ether.ETH_TYPE_ARP, eth_src=FAKESERVERMAC, in_port=FAKEPORT, arp_op=arp.ARP_REQUEST, vlan_vid=vlan_id),
                     [parser.OFPInstructionGotoTable(TO_COPRO_TABLE)]),
                ):
                mods.append(parser.OFPFlowMod(
                    datapath=datapath,
                    command=ofp.OFPFC_ADD,
                    table_id=table_id,
                    priority=1,
                    match=match,
                    instructions=instructions))
        self.send_mods(datapath, mods)
