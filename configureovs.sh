#!/bin/bash

# Configure pipette's OVS switch.
echo "Configuring OVS switch for pipette"

remove_int_ip() {
  local int="$1"
  sudo ip addr flush dev "$int"
  sudo ip link set "$int" up
}

sudo ovs-vsctl --if-exists del-br "$BR"
echo "Configuring bridge"
sudo ovs-vsctl add-br "$BR"
echo "Adding ports"
sudo ovs-vsctl add-port "$BR" "$COPROINT" -- set Interface "$COPROINT" ofport_request="$COPROPORT"
sudo ovs-vsctl add-port "$BR" "$FAKEINT" -- set Interface "$FAKEINT" ofport_request="$FAKEPORT" type=internal
echo "Setting controller"
sudo ovs-vsctl set-controller "$BR" tcp:127.0.0.1:"$OF"

for i in $COPROINT $FAKEINT $BR ; do
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
