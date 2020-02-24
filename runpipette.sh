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
      -i,  fakeips       fake ip for fake services, space delimitted (will be proxied from real IPS)
      -h,  help          print this help
      -b,  bridge        name of ovs bridge to create
      -p,  port          pipette port
      -v,  vlans         coprocessor vlans, space delimitted
      -r,  record        record traffic captured by pipette should be followed by location then size of file i.e.: -r /pcaps.file.pcap 50"
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
            -i|fakeips)
                NFVIPS=""
                while [[ "$2" != -* && -n "$2" ]]
                do
                  NFVIPS+="$2 "
                  shift
                done 
                ;;
            -v|vlans)
                VLANS=""
                while [[ "$2" != -* && -n "$2" ]]
                do
                  VLANS+="$2 "
                  shift
                done 
                ;;
            -b|bridge)
                BR="$2"
                shift
                ;;
            -p|port)
                OF="$2"
                shift
                ;;
            -r|record)
                RECORD=1
                PCAP_LOCATION="$2"
                shift
                FILE_SIZE="$2"
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


remove_int_ip() {
  local int="$1"
  sudo ip addr flush dev "$int"
  sudo ip link set "$int" up
}


# Configure pipette's OVS switch.
echo "Configuring OVS switch for pipette"
sudo ip link add dev "$FAKEINT" type veth peer name "ovs$FAKEINT"
for i in $COPROINT $FAKEINT ovs$FAKEINT ; do
  remove_int_ip "$i"
done

for ((i=0; i< "${#VLANS[@]}"; i++)) ; do
  vlan="${VLANS[$i]}"
  nfvip="${NFVIPS[$i]}"
  fakeintvlan=${FAKEINT}.${vlan}
  sudo ip link add link "$FAKEINT" name "$fakeintvlan" type vlan id "$vlan"
  sudo ip link set dev "$fakeintvlan" address "$FAKESERVERMAC"
  remove_int_ip "$fakeintvlan"
  sudo ip addr add "$nfvip" dev "$fakeintvlan"
done


sudo ovs-vsctl --if-exists del-br "$BR"

echo "Configuring bridge"
sudo ovs-vsctl add-br "$BR"
echo "Adding ports"
sudo ovs-vsctl add-port "$BR" "$COPROINT" -- set Interface "$COPROINT" ofport_request="$COPROPORT"
sudo ovs-vsctl add-port "$BR" "ovs$FAKEINT" -- set Interface "ovs$FAKEINT" ofport_request="$FAKEPORT"
echo "Setting controller"
sudo ovs-vsctl set-controller "$BR" tcp:127.0.0.1:"$OF"


if [ $RECORD -ne 0 ]; then
    echo "Starting tcpdump on interface $COPROINT"
    sudo tcpdump -i "$COPROINT" -w "$PCAP_LOCATION" -C "$FILE_SIZE" -Z root &
fi


# docker build -f $DFILE . -t cyberreboot/pipette && docker run -e NFVIPS=$NFVIPS -e FAKESERVERMAC=$FAKESERVERMAC -e FAKECLIENTMAC=$FAKECLIENTMAC -e VLANS=$VLANS -p 127.0.0.1:$OF:6653 -ti cyberreboot/pipette
ryu-manager --verbose --ofp-tcp-listen-port "$OF" pipette.py
