#!/usr/bin/env python

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
import unittest
from pipette import Pipette

from ryu.lib.packet import ethernet, icmpv6, ipv6, packet, vlan
from ryu.ofproto import ether


class FakePort:

    port_no = 1
    name = 'fakey'
    state = 0


class FakeDP:

    def __init__(self):
        self.ports = {1: FakePort()}
        self.msgs = []

    def send_msg(self, msg):
        self.msgs.append(msg)


class FakeEv:

    def __init__(self):
        self.dp = FakeDP()



class PipetteSmokeTest(unittest.TestCase):  # pytype: disable=module-attr
    """Test bare instantiation of controller classes."""



    def test_smoke_connect(self):
        for nfvip in ('192.168.1.1/16', 'fc00::1/64'):
            pipette = Pipette(dpset={})
            pipette.NFVIPS = [ipaddress.ip_interface(nfvip)]
            assert pipette.dp_connect(FakeEv()) is None


    def test_smoke_packet_in(self):
        nd_solicit = packet.Packet()
        eth_src = '01:02:03:04:05:06'
        eth_dst = 'ff:ff:ff:ff:ff:ff'
        src_ip = 'fc00::1'
        dst_ip = 'fc00::2'
        vid = 2
        for protocol in (
                ethernet.ethernet(eth_dst, eth_src, ether.ETH_TYPE_8021Q),
                vlan.vlan(vid=vid, ethertype=ether.ETH_TYPE_IPV6),
                ipv6.ipv6(src=src_ip, dst=dst_ip, nxt=socket.IPPROTO_ICMPV6, hop_limit=255),
                icmpv6.icmpv6(
                    type_=icmpv6.ND_NEIGHBOR_SOLICIT,
                    data=icmpv6.nd_neighbor(dst=src_ip, option=icmpv6.nd_option_tla(hw_src=eth_src), res=7))):
            nd_solicit.add_protocol(protocol)
        nd_solicit.serialize()


        fake_dp = FakeDP()
        pipette = Pipette(dpset={})

        class FakeMsg:

            def __init__(self):
                self.datapath = fake_dp
                self.match = {'in_port': pipette.FAKEPORT}
                self.data = nd_solicit.data


        class FakePiEv:

            def __init__(self):
                self.msg = FakeMsg()


        pipette = Pipette(dpset={})
        pipette.packet_in_handler(FakePiEv())
        assert fake_dp.msgs



if __name__ == "__main__":
    unittest.main()  # pytype: disable=module-attr
