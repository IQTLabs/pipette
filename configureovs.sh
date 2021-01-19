#!/bin/bash

while ovs-vsctl show; [ $? -ne 0 ]; do
  sleep 1
  echo waiting for OVS
done

set -e

# Configure pipette's OVS switch.
echo "Configuring OVS bridge $BR for pipette"

remove_int_ip() {
  local int="$1"
  ip addr flush dev "$int"
  ip link set "$int" up
}

ovs-vsctl --if-exists del-br "$BR"
echo "Configuring bridge"
ovs-vsctl add-br "$BR"
echo "Adding ports"
ovs-vsctl add-port "$BR" "$COPROINT" -- set Interface "$COPROINT" ofport_request="$COPROPORT"
ovs-vsctl add-port "$BR" "$FAKEINT" -- set Interface "$FAKEINT" ofport_request="$FAKEPORT" type=internal
echo "Setting controller"
ovs-vsctl set-controller "$BR" tcp:127.0.0.1:"$OF"

for i in $COPROINT $FAKEINT $BR ; do
  remove_int_ip "$i"
done

for ((i=0; i< "${#VLANS[@]}"; i++)) ; do
  vlan="${VLANS[$i]}"
  nfvip="${NFVIPS[$i]}"
  fakeintvlan=${FAKEINT}.${vlan}
  ip link add link "$FAKEINT" name "$fakeintvlan" type vlan id "$vlan"
  ip link set dev "$fakeintvlan" address "$FAKESERVERMAC"
  remove_int_ip "$fakeintvlan"
  ip addr add "$nfvip" dev "$fakeintvlan"
done

while [[ "$(ovs-ofctl dump-flows $BR)" == "" ]] ; do
  sleep 1
  echo waiting for flows in $BR
done
