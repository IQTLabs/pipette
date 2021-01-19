# pipette
![test](https://github.com/IQTLabs/pipette/workflows/test/badge.svg) [![codecov](https://codecov.io/gh/IQTLabs/pipette/branch/master/graph/badge.svg)](https://codecov.io/gh/IQTLabs/pipette) ![buildx](https://github.com/IQTLabs/pipette/workflows/buildx/badge.svg)

## An SDN/NFV coprocessor controller.
Pipette is a tool that allows users to multiplex SDN coprocessing by implementing transparent L3 NAT. Pipette does this by creating a virtual network behind your coprocessor port and then acting as the SDN controller of that network. Packets are seamlessly switched to their appropriate destination using [Ryu](https://osrg.github.io/ryu/).

## Usage

*NOTE: Running pipette outside of Docker, is deprecated and will be removed in a future release.*

 1. Edit configuration in `.env`, as below (note `.env` is used even when not using Docker).
 1. If using Docker, start pipette with `docker-compose up -d`. If not using Docker, start pipette with `./runpipette.sh.`
 1. Start fake services listening on the NFVIP address assigned to the fake interface (Eg, IP of `fake0.2` for VLAN 2 - pipette manages this interface and assigns the NFVIP). Fake services do not have to be in Docker.
 1. When finished, `docker-compose down` if using Docker, or `./shutdownpipette.sh`

### Configuration
#### Required
 1. COPROINT - the interface that will receive coprocessed packets
 1. VLANS - Space delimitted list of VLANs to coprocess from, must match a VLAN in FAUCET ACL rule
 1. NFVIPS - IPs to send coprocessed packets to. Must be a /16 if IPv4, or /96 if IPv6. There must be the same number of IPs in the list as VLANs.

#### Optional
 1. FAKEINT - name of interface created for fake services to run on (default fake0)
 1. FAKESERVERMAC - MAC to be assigned to the coprocessing server
 1. FAKECLIENTMAC - MAC to be assigned to the coprocessing client
 1. BR - name of OVS bridge to be created
 1. OF - Pipette OpenFlow port number
 1. COPROPORT - - OpenFlow port number exposed from $COPROINT to OVS
 1. FAKEPORT - OpenFlow port number to correspond from OVS to `$FAKEINT`
 1. RECORD - 0 to not store pcaps passing through `$COPROINT`, anything else to store them
 1. PCAP_LOCATION - filename of store pcaps
 1. PIPETTE_TEMP_DIR temp directory to store process info
