#!/bin/bash

source ./pipetteconf.sh

function show_help()
{
    echo "pipette coprocessor setup (uses sudo)

    Usage: runpipette [option]
    Options:
      -c,  coproint      interface to send coprocessed traffic to
      -f,  fakeint       interface created for fake services to run on
      -m,  fakemac       fake mac for fake interface
      -fch, fakeclientmac fake client mac address
      -i,  fakeip        fake ip for fake services(will be proxied from real IPS)
      -h,  help          print this help
      -b,  bridge        name of ovs bridge to create
      -p,  port          pipette port"
}

function check_args()
{
    while [ $# -gt 1 ]; do
        case $1 in
            -c|coproint)
                COPROINT="$2"
                shift
                ;;
            -f|fakeint)
                FAKEINT="$2"
                shift
                ;;
            -m|fakemac)
                FAKESERVERMAC="$2"
                shift
                ;;
            -fch|fakeclientmac)
                FAKECLIENTMAC="$2"
                shift
                ;;
            -i|fakeip)
                NFVIP="$2"
                shift
                ;;
            -b|bridge)
                BR="$2"
                shift
                ;;
            -p|port)
                OF="$2"
                shift
                ;;
            -h|\?|help)
                show_help
                exit
                ;;
        esac
        shift
    done
}

if [ $# -gt 0 ]; then
    check_args "$@"
fi

# Configure pipette's OVS switch.
# Remove all IP addresses, disable IPv6.
echo "Configuring OVS switch for pipette"
sudo ip link add dev $FAKEINT type veth peer name ovs$FAKEINT
sudo ip link set dev $FAKEINT address $FAKESERVERMAC
echo "Removing IPs"
for i in $COPROINT $FAKEINT ovs$FAKEINT ; do
  sudo ip addr flush dev $i
  sudo ip link set $i up
done
sudo ip addr add $NFVIP dev $FAKEINT

sudo ovs-vsctl --if-exists del-br $BR

echo "Configuring bridge"
sudo ovs-vsctl add-br $BR
echo "Adding ports"
for i in $COPROINT ovs$FAKEINT ; do
  sudo ovs-vsctl add-port $BR $i
done
echo "Setting controller"
sudo ovs-vsctl set-controller $BR tcp:127.0.0.1:$OF

# docker build -f $DFILE . -t anarkiwi/pipette && docker run -e NFVIP=$NFVIP -e FAKESERVERMAC=$FAKESERVERMAC -e FAKECLIENTMAC=$FAKECLIENTMAC -e VLAN=$VLAN -p 127.0.0.1:$OF:6653 -ti anarkiwi/pipette
ryu-manager --verbose --ofp-tcp-listen-port $OF pipette.py
