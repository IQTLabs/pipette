#!/bin/bash

##
# Required config
## 

# interface connected to FAUCET coprocessor port.
COPROINT=enx0023565c8859
# address fake services will be run on (will be proxied from real IPs)
NFVIP=192.168.101.1/24
# FAUCET VLAN where fake services will appear.
VLAN=2
# interface that will be created for fake services to run on.
FAKEINT=fake0
DFILE=Dockerfile.pi

##
# Optional config
##

# Reserved MAC addresses for fake services to use to talk to clients.
FAKESERVERMAC=0e:00:00:00:00:66
FAKECLIENTMAC=0e:00:00:00:00:67
# OVS bridge name
BR=copro0
# pipette OF port
OF=6699

## Configure pipette's OVS switch and pipette.
# Remove existing veth/OVS bridge.
if test -L "/sys/class/net/$FAKEINT"; then
    ip link del dev $FAKEINT || exit 1
fi
ovs-vsctl --if-exists del-br $BR || exit 1

# Add veth, remove existing IPs.
ip link add dev $FAKEINT type veth peer name ovs$FAKEINT
ip link set $FAKEINT address $FAKESERVERMAC
for i in $COPROINT $FAKEINT ovs$FAKEINT ; do
  echo 1 > /proc/sys/net/ipv6/conf/$i/disable_ipv6
  ip addr flush $i
  ip link set dev $i up
done
ip addr add $NFVIP dev $FAKEINT
ovs-vsctl add-br $BR
for i in $COPROINT ovs$FAKEINT ; do
  ovs-vsctl add-port $BR $i
done
ovs-vsctl set-controller $BR tcp:127.0.0.1:$OF

docker build -f $DFILE . -t anarkiwi/pipette && docker run -e NFVIP=$NFVIP -e FAKESERVERMAC=$FAKESERVERMAC -e FAKECLIENTMAC=$FAKECLIENTMAC -e VLAN=$VLAN -p 127.0.0.1:$OF:6653 -ti anarkiwi/pipette
