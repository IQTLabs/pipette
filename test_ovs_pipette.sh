#!/bin/bash

# requires OVS and Ryu
# Test that NAT works.

set -e

OF=6699
TMPDIR=$(mktemp -d)
SANDBOX=$TMPDIR/ovs-sandbox.sh
TESTSCRIPT=$TMPDIR/test-script.sh
TESTOUTPUT=$TMPDIR/test-output.txt

wget -q -O$SANDBOX https://raw.githubusercontent.com/openvswitch/ovs/master/tutorial/ovs-sandbox
chmod +x $SANDBOX

cat > $TESTSCRIPT <<- EOTESTSCRIPT
sleep 5
ovs-vsctl add-br copro0 \
         -- set bridge copro0 other-config:datapath-id=0000000000000001 \
         -- add-port copro0 copro -- set interface copro ofport_request=1 \
         -- add-port copro0 fake -- set interface fake ofport_request=2 \
         -- set-controller copro0 tcp:127.0.0.1:$OF \
         -- set controller copro0 connection-mode=out-of-band

while [ "\$(ovs-vsctl show|grep -i 'is_connected: true')" = "" ] ; do
  sleep 1
  echo .
done

ovs-appctl ofproto/trace copro0 in_port=copro,dl_vlan=2,dl_src=0e:00:00:00:00:01,dl_dst=0e:00:00:00:00:02,eth_type=0x800,nw_src=192.168.2.5,nw_dst=192.168.2.1,nw_proto=6,tcp_src=9999,tcp_dst=80 -generate

ovs-appctl ofproto/trace copro0 in_port=fake,dl_vlan=2,dl_src=0e:00:00:00:00:66,dl_dst=0e:00:00:00:00:67,eth_type=0x800,nw_src=10.10.0.1,nw_dst=10.10.5.1,nw_proto=6,tcp_src=80,tcp_dst=9999 -generate
EOTESTSCRIPT

ryu-manager pipette.py --verbose --ofp-tcp-listen-port $OF &
RPID=$!

chmod +x $TESTSCRIPT
SHELL=$TESTSCRIPT $SANDBOX > $TESTOUTPUT
kill $RPID

cat $TESTSCRIPT
cat $TESTOUTPUT
grep "Final flow" $TESTOUTPUT

# inbound NAT entry
grep -q "Final flow: tcp,reg1=0x2,reg2=0x1,reg7=0xa0a0501,in_port=1,dl_vlan=2,dl_vlan_pcp=0,vlan_tci1=0x0000,dl_src=0e:00:00:00:00:67,dl_dst=0e:00:00:00:00:66,nw_src=10.10.5.1,nw_dst=10.10.0.1,nw_tos=0,nw_ecn=0,nw_ttl=0,tp_src=9999,tp_dst=80,tcp_flags=0" $TESTOUTPUT
# outbound NAT entry
grep -q "Final flow: tcp,in_port=2,dl_vlan=2,dl_vlan_pcp=0,vlan_tci1=0x0000,dl_src=0e:00:00:00:00:02,dl_dst=0e:00:00:00:00:01,nw_src=192.168.2.1,nw_dst=192.168.2.5,nw_tos=0,nw_ecn=0,nw_ttl=0,tp_src=80,tp_dst=9999,tcp_flags=0" $TESTOUTPUT

rm -rf $TMPDIR

echo PASS
