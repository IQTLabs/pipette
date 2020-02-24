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
import logging
import socket
import os
import sys
import netaddr
from ryu.base import app_manager
from ryu.controller import dpset, ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import arp, ethernet, icmpv6, ipv6, packet, vlan
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
ALL_TABLES = (INTF_TABLE, FROM_COPRO_TABLE, TO_COPRO_TABLE)


class Pipette(app_manager.RyuApp):

    OFP_VERSIONS = [ofp.OFP_VERSION]
    _CONTEXTS = {
        'dpset': dpset.DPSet,
    }


    @staticmethod
    def send_mods(datapath, mods):
        for mod in mods:
            datapath.send_msg(mod)


    @staticmethod
    def apply_actions(actions):
        return [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]


    def nat_actions(self, eth_type, nfvip, reg0):
        ip_ver = nfvip.ip.version
        ip_src_nxm = 'ipv%u_src_nxm' % ip_ver
        ip_dst_nxm = 'ipv%u_dst_nxm' % ip_ver
        ipbits = nfvip.ip.max_prefixlen
        return [
            # we have to load output port numbers into reg1 and reg2 because NXFlowSpecOutput() won't take a literal.
            parser.NXActionRegLoad(value=FAKEPORT, dst='reg1', ofs_nbits=nicira_ext.ofs_nbits(0, 15)),
            parser.NXActionRegLoad(value=COPROPORT, dst='reg2', ofs_nbits=nicira_ext.ofs_nbits(0, 15)),
            # now program an inbound flow to perform NAT.
            parser.NXActionLearn(
                table_id=FROM_COPRO_TABLE,
                priority=2,
                hard_timeout=IDLE,
                specs=[
                    parser.NXFlowSpecMatch(src=eth_type, dst=('eth_type_nxm', 0), n_bits=16),
                    parser.NXFlowSpecMatch(src=(ip_src_nxm, 0), dst=(ip_src_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecMatch(src=(ip_dst_nxm, 0), dst=(ip_dst_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecLoad(src=int(FAKECLIENTMAC), dst=('eth_src_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=int(FAKESERVERMAC), dst=('eth_dst_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=(reg0, 0), dst=(ip_src_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecLoad(src=int(nfvip.ip), dst=(ip_dst_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecOutput(src=('reg1', 0), dst='', n_bits=16),
                ]),
            # now program outbound an outbound flow.
            parser.NXActionLearn(
                table_id=TO_COPRO_TABLE,
                priority=2,
                idle_timeout=IDLE,
                specs=[
                    parser.NXFlowSpecMatch(src=eth_type, dst=('eth_type_nxm', 0), n_bits=16),
                    parser.NXFlowSpecMatch(src=int(nfvip.ip), dst=(ip_src_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecMatch(src=(reg0, 0), dst=(ip_dst_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecLoad(src=('eth_dst_nxm', 0), dst=('eth_src_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=('eth_src_nxm', 0), dst=('eth_dst_nxm', 0), n_bits=48),
                    parser.NXFlowSpecLoad(src=(ip_dst_nxm, 0), dst=(ip_src_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecLoad(src=(ip_src_nxm, 0), dst=(ip_dst_nxm, 0), n_bits=ipbits),
                    parser.NXFlowSpecOutput(src=('reg2', 0), dst='', n_bits=16),
                ]),
            # now that future flows are programmed, handle the packet we have.
            parser.OFPActionSetField(eth_src=FAKECLIENTMAC),
            parser.OFPActionSetField(eth_dst=FAKESERVERMAC),
            parser.NXActionRegMove(src_field=reg0, dst_field=('ipv%u_src' % ip_ver), n_bits=ipbits, src_ofs=0, dst_ofs=0),
            parser.OFPActionSetField(**{'ipv%u_dst' % ip_ver: str(nfvip.ip)}),
            parser.OFPActionOutput(FAKEPORT)
         ]


    def natv6_flows(self, nfvip):
        return self.apply_actions([])


    def natv4_flows(self, nfvip):
        # configure automatic learning.
        nat_base = nfvip.network.network_address
        # pylint: disable=no-member
        return self.apply_actions([
            # first, calculate src NAT address, leave in reg0.
            # Assuming ipv4_src is 192.168.2.5, ipv4_dst is 192.168.2.1, and NFVIP is 10.10.0.1/24
            # ipv4_src becomes 10.10.5.1 (low octet of dst is LSB, then low octet of src).
            parser.NXActionRegLoad(value=int(nat_base), dst='xxreg0', ofs_nbits=nicira_ext.ofs_nbits(0, 31)),
            parser.NXActionRegMove(src_field='ipv4_src', dst_field='xxreg0', n_bits=8, src_ofs=0, dst_ofs=8),
            parser.NXActionRegMove(src_field='ipv4_dst', dst_field='xxreg0', n_bits=8, src_ofs=0, dst_ofs=0),
         ] + self.nat_actions(ether.ETH_TYPE_IP, nfvip, 'xxreg0'))


    @staticmethod
    def common_reply_actions():
        # pylint: disable=no-member
        return [
            parser.NXActionRegMove(src_field='eth_src', dst_field='eth_dst', n_bits=48, src_ofs=0, dst_ofs=0),
            parser.OFPActionSetField(eth_src=FAKECLIENTMAC),
            parser.OFPActionOutput(ofp.OFPP_IN_PORT)
        ]


    def arp_reply_actions(self):
        # pylint: disable=no-member
        common_reply = self.common_reply_actions()
        return self.apply_actions([
            parser.NXActionRegLoad(value=arp.ARP_REPLY, dst='arp_op', ofs_nbits=nicira_ext.ofs_nbits(0, 2)),
            parser.NXActionRegMove(src_field='arp_sha', dst_field='arp_tha', n_bits=48, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='arp_tpa', dst_field='xxreg0', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='arp_spa', dst_field='arp_tpa', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.NXActionRegMove(src_field='xxreg0', dst_field='arp_spa', n_bits=32, src_ofs=0, dst_ofs=0),
            parser.OFPActionSetField(arp_sha=FAKECLIENTMAC),
            ] + common_reply)


    @staticmethod
    def report_port(of_port):
        PORT_NAMES = {
            COPROPORT: 'COPROPORT',
            FAKEPORT: 'FAKEPORT',
        }
        port_name = PORT_NAMES.get(of_port.port_no, None)
        if not port_name:
            return
        blocked_down_state = (
            (of_port.state & ofp.OFPPS_BLOCKED) or (of_port.state & ofp.OFPPS_LINK_DOWN))
        if blocked_down_state:
            port_state = 'down'
        else:
            port_state = 'up'
        logging.warning(
            'PORT %s (%u) %s: %s', of_port.name, of_port.port_no, port_state, of_port)


    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER) # pylint: disable=no-member
    def port_status_handler(self, ryu_event):
        self.report_port(ryu_event.msg.desc)


    @staticmethod
    def tcp_udp_flows(vlan_id, nfvip, eth_type, nat_flows):
        return (
            # Learn from coprocessor port/do inbound translation.
            (FROM_COPRO_TABLE, parser.OFPMatch(eth_type=eth_type, vlan_vid=vlan_id),
             nat_flows(nfvip)),
            # Packets from coprocessor go to tuple inbound table.
            (INTF_TABLE, parser.OFPMatch(
                eth_type=eth_type, ip_proto=socket.IPPROTO_TCP, in_port=COPROPORT, vlan_vid=vlan_id),
             [parser.OFPInstructionGotoTable(FROM_COPRO_TABLE)]),
            (INTF_TABLE, parser.OFPMatch(
                eth_type=eth_type, ip_proto=socket.IPPROTO_UDP, in_port=COPROPORT, vlan_vid=vlan_id),
             [parser.OFPInstructionGotoTable(FROM_COPRO_TABLE)]),
            # Packets from fake interface go outbound table.
            (INTF_TABLE, parser.OFPMatch(
                eth_type=eth_type, ip_proto=socket.IPPROTO_TCP, in_port=FAKEPORT, vlan_vid=vlan_id),
             [parser.OFPInstructionGotoTable(TO_COPRO_TABLE)]),
            (INTF_TABLE, parser.OFPMatch(
                eth_type=eth_type, ip_proto=socket.IPPROTO_UDP, in_port=FAKEPORT, vlan_vid=vlan_id),
             [parser.OFPInstructionGotoTable(TO_COPRO_TABLE)]))



    @set_ev_cls(dpset.EventDP, dpset.DPSET_EV_DISPATCHER)
    @set_ev_cls(dpset.EventDPReconnected, dpset.DPSET_EV_DISPATCHER)
    def dp_connect(self, ryu_event):
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
        datapath = ryu_event.dp
        for of_port in datapath.ports.values():
            self.report_port(of_port)
        mods = []
        # Drop all flows.
        mods.append(parser.OFPFlowMod(
            datapath=datapath,
            command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
        ))
        # Default deny all tables
        for table_id in ALL_TABLES:
            mods.append(parser.OFPFlowMod(
                datapath=datapath,
                command=ofp.OFPFC_ADD,
                table_id=table_id,
                priority=0,
                instructions=[]))


        def ipv6_flows(vlan_id, _nfvip):
            return (
                (INTF_TABLE, parser.OFPMatch(eth_type=ether.ETH_TYPE_IPV6, vlan_vid=vlan_id, ip_proto=socket.IPPROTO_ICMPV6, icmpv6_type=icmpv6.ND_NEIGHBOR_SOLICIT),
                 self.apply_actions([parser.OFPActionOutput(ofp.OFPP_CONTROLLER)])),) + self.tcp_udp_flows(vlan_id, nfvip, ether.ETH_TYPE_IPV6, self.natv6_flows)


        def ipv4_flows(vlan_id, nfvip):
            return (
                # Program OVS to respond to ARP on fake port.
                (TO_COPRO_TABLE, parser.OFPMatch(eth_type=ether.ETH_TYPE_ARP, vlan_vid=vlan_id),
                 self.arp_reply_actions()),
                (INTF_TABLE, parser.OFPMatch(
                    eth_type=ether.ETH_TYPE_ARP, eth_src=FAKESERVERMAC, in_port=FAKEPORT, arp_op=arp.ARP_REQUEST, vlan_vid=vlan_id),
                 [parser.OFPInstructionGotoTable(TO_COPRO_TABLE)])) + self.tcp_udp_flows(vlan_id, nfvip, ether.ETH_TYPE_IP, self.natv4_flows)


        for nfvlan, nfvip in zip(VLANS, NFVIPS):
            vlan_id = (nfvlan | ofp.OFPVID_PRESENT)
            if nfvip.version == 6:
                flows = ipv6_flows
            else:
                flows = ipv4_flows
            for table_id, match, instructions in flows(vlan_id, nfvip):
                mods.append(parser.OFPFlowMod(
                    datapath=datapath,
                    command=ofp.OFPFC_ADD,
                    table_id=table_id,
                    priority=1,
                    match=match,
                    instructions=instructions))
        self.send_mods(datapath, mods)

    # TODO: need packet in handler for IPv6 only, as OF1.3 won't let us set OFPXMT_OFB_ICMPV6_ND_RESERVED
    # See https://docs.opendaylight.org/projects/netvirt/en/latest/specs/fluorine/ovs_based_na_responder_for_gw.html.
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER) # pylint: disable=no-member
    def packet_in_handler(self, event):
        if event.msg.match['in_port'] != FAKEPORT:
            return
        pkt = packet.Packet(event.msg.data)
        eth_protocol = pkt.get_protocol(ethernet.ethernet)
        vlan_protocol = pkt.get_protocol(vlan.vlan)
        ipv6_protocol = pkt.get_protocol(ipv6.ipv6)
        icmpv6_protocol = pkt.get_protocol(icmpv6.icmpv6)
        if not (eth_protocol and vlan_protocol and ipv6_protocol and icmpv6_protocol):
            return
        if icmpv6_protocol.type_ != icmpv6.ND_NEIGHBOR_SOLICIT:
            return
        if int(ipaddress.ip_address(ipv6_protocol.src)) == 0:
            return
        src_ip = ipaddress.ip_address(icmpv6_protocol.data.dst)
        if src_ip.is_reserved:
            return
        eth_dst = eth_protocol.src
        dst_ip = ipv6_protocol.src
        eth_src = FAKECLIENTMAC
        vid = vlan_protocol.vid
        reply = packet.Packet()
        for protocol in (
                ethernet.ethernet(eth_dst, eth_src, ether.ETH_TYPE_8021Q),
                vlan.vlan(vid=vid, ethertype=ether.ETH_TYPE_IPV6),
                ipv6.ipv6(src=src_ip, dst=dst_ip, nxt=socket.IPPROTO_ICMPV6, hop_limit=255),
                icmpv6.icmpv6(
                    type_=icmpv6.ND_NEIGHBOR_ADVERT,
                    data=icmpv6.nd_neighbor(dst=src_ip, option=icmpv6.nd_option_tla(hw_src=eth_src), res=7))):
            reply.add_protocol(protocol)
        reply.serialize()
        out = parser.OFPPacketOut(
            datapath=event.msg.datapath,
            buffer_id=ofp.OFP_NO_BUFFER,
            in_port=ofp.OFPP_CONTROLLER,
            actions=[parser.OFPActionOutput(FAKEPORT)], data=reply.data)
        self.send_mods(event.msg.datapath, [out])
