#!/bin/bash

while ovs-vsctl show; [ $? -ne 0 ]; do
  sleep 1
  echo waiting for OVS
done

set -e

OLDBR=copro${ID}
BR=pipette${ID}
FAKEINT=fake${ID}
FAKESERVERMAC=${FAKEMACPREFIX}:${ID}:${COPROPORT}
FAKECLIENTMAC=${FAKEMACPREFIX}:${ID}:${FAKEPORT}

# Configure pipette's OVS switch.
echo "Configuring OVS bridge $BR for pipette ID ${ID}"

remove_int_ip() {
  local int="$1"
  ip addr flush dev "$int"
  ip link set "$int" up
}

ovs-vsctl --if-exists del-br "$OLDBR"
ovs-vsctl --if-exists del-br "$BR"
echo "Configuring bridge"
ovs-vsctl add-br "$BR"
echo "Adding ports"
ovs-vsctl add-port "$BR" "$COPROINT" -- set Interface "$COPROINT" ofport_request="$COPROPORT"
ovs-vsctl add-port "$BR" "$FAKEINT" -- set Interface "$FAKEINT" ofport_request="$FAKEPORT" type=internal
ovs-ofctl del-flows "$BR"
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

flows=""
while [[ "$flows" == "" ]] ; do
  flows=$(ovs-ofctl dump-flows $BR table=2|grep cookie|cat)
  sleep 1
  echo waiting for flows in $BR
done

IFS=, read -ra tcmap <<< "$TC"
for tc in "${tcmap[@]}" ; do
  IFS=: read -ra tcentry <<< "$tc"
  invid=${tcentry[0]}
  outvid=${tcentry[1]}
  tcpol=${tcentry[2]}
  suffix=${ID}v${invid}
  tcint=tc${suffix}
  tcbr=tcbr${suffix}
  echo configure tc map, input vid $invid, output vid $outvid, via $tcint/$tcbr
  ovs-vsctl add-port "$BR" "$tcint" -- set Interface "$tcint" ofport_request="$invid" type=internal
  ovs-ofctl add-flow "$BR" priority=64738,in_port=$invid,actions=output:$COPROPORT
  ovs-ofctl add-flow "$BR" priority=64738,in_port=$COPROPORT,dl_vlan=$invid,actions=mod_vlan_vid=$outvid,output:$invid
  ip link del $tcbr 2> /dev/null || true
  ip link add name $tcbr type bridge
  ip link set dev $tcbr up
  ip link set dev $tcint up
  ip link set dev $tcint master $tcbr
  bridge link set dev $tcint hairpin on
  tc qdisc add dev $tcint $tcpol
done

echo configuration successful
