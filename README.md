# pipette
![test](https://github.com/IQTLabs/pipette/workflows/test/badge.svg) [![codecov](https://codecov.io/gh/IQTLabs/pipette/branch/master/graph/badge.svg)](https://codecov.io/gh/IQTLabs/pipette) ![buildx](https://github.com/IQTLabs/pipette/workflows/buildx/badge.svg)

## An SDN/NFV coprocessor controller.
Pipette is a tool that allows users to multiplex SDN coprocessing by implementing transparent L3 NAT. Pipette does this by creating a virtual network behind your coprocessor port and then acting as the SDN controller of that network. Packets are seamlessly switched to their appropriate destination using [Ryu](https://osrg.github.io/ryu/).

## Usage

 1. If an OVS container is not already present, start OVS: `docker-compose -f docker-compose-ovs.yml up -d`
 1. Start pipette: `COPROINT=<ethX> VLANS=<VLANs> NFVIPS=<NFVIPs> OF=<OF TCP port> ID=0 docker-compose -p 0 up -d` (see Configuration section - example `COPROINT=eth1 VLANS=2 NFVIPS=10.10.0.1/16 OF=6699 ID=0 docker-compose -p 0 up -d`.
 1. Start fake services listening on the NFVIP address assigned to the fake interface (Eg, IP of `fake0.2` for VLAN 2 - pipette manages this interface and assigns the NFVIP). Fake services do not have to be in Docker.
 1. When finished, `docker-compose down`.
 1. If you want to run pipette on multiple interfaces, specify different ID and project number as well as interfaces and NFVIPs (the same VLANs can be coprocessed differently on different interfaces - example `COPROINT=eth2 VLANS=2 NFVIPS=10.20.0.1/16 OF=6799 ID=1 docker-compose -p 1 up -d`)

### Configuration
#### Required
 1. COPROINT - the interface that will receive coprocessed packets
 1. VLANS - Space delimitted list of VLANs to coprocess from, must match a VLAN in FAUCET ACL rule
 1. NFVIPS - IPs to send coprocessed packets to. Must be a /16 if IPv4, or /96 if IPv6. There must be the same number of IPs in the list as VLANs.
 1. OF - OpenFlow TCP port for pipette to use
