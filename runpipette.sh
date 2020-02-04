#!/bin/bash

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

function show_help()
{
    echo "pipette coprocessor setup (uses sudo)

    Usage: runpipette [option]
    Options:
      -c,  coproint      interface to send coprocessed traffic to
      -f,  fakeint       interface created for fake services to run on
      -m,  fakemac       fake mack for fake interface
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
else # print help
    show_help
    exit
fi

# Configure pipette's OVS switch.
# Remove all IP addresses, disable IPv6.
echo "Configuring OVS switch for pippette"
sudo ip link add dev $FAKEINT type veth peer name ovs$FAKEINT
echo "removing IPs"
for i in $COPROINT $FAKEINT ovs$FAKEINT ovs-system ; do
  if ifconfig $i | grep inet ; then
    sudo ip addr flush $i
  fi
done
echo "Configuring interfaces"
sudo ifconfig $COPROINT up
sudo ifconfig ovs$FAKEINT up
sudo ifconfig $FAKEINT hw ether $FAKESERVERMAC $FAKESERVERMAC up

if ifconfig $BR; then
  echo "Removing existing OVS bridge $BR"
  sudo ovs-vsctl del-br $BR
fi

echo "Configuring bridge"
sudo ovs-vsctl add-br $BR
sudo ovs-ofctl del-flows $BR
echo "adding flows"
for i in $COPROINT ovs$FAKEINT ; do
  sudo ovs-vsctl add-port $BR $i
done
echo "setting controller"
sudo ovs-vsctl set-controller $BR tcp:127.0.0.1:$OF

docker build -f $DFILE . -t anarkiwi/pipette && docker run -e NFVIP=$NFVIP -e FAKESERVERMAC=$FAKESERVERMAC -e FAKECLIENTMAC=$FAKECLIENTMAC -e VLAN=$VLAN -p 127.0.0.1:$OF:6653 -ti anarkiwi/pipette
