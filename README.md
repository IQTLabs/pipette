# pipette
![test](https://github.com/CyberReboot/pipette/workflows/test/badge.svg) [![codecov](https://codecov.io/gh/CyberReboot/pipette/branch/master/graph/badge.svg)](https://codecov.io/gh/CyberReboot/pipette) ![buildx](https://github.com/CyberReboot/pipette/workflows/buildx/badge.svg)

## An SDN/NFV coprocessor controller.
Pipette is a tool that allows users to multiplex SDN coprocessing by implementing transparent L3 NAT. Pipette does this by creating a virtual network behind your coprocessor port and then acting as the SDN controller of that network. Packets are seamlessly switched to their appropriate destination using [Ryu](https://osrg.github.io/ryu/).

## Usage
### Configuration
#### Required
 1. COPROINT - the interface that will receive coprocessed packets
 1. NFVIPS - IPs to send coprocessed packets to. Must be a /16
 1. VLANS - Space delimitted list of vlans to coprocess from, must match a vlan in ACL rule
 1. FAKEINT - interface created for fake services to run on
 1. DFILE - Dockerfile to use to run pipette. should be set based on hardware use

#### Optional
 1. FAKESERVERMAC - MAC to be assigned to the coprocessing server
 1. FAKECLIENTMAC - MAC to be assigned to the coprocessing client
 1. BR - name of OVS bridge to be created
 1. OF - Pipette OpenFlow port number
 1. COPROPORT - - OpenFlow port number exposed from $COPROINT to OVS
 1. FAKEPORT - OpenFlow port number to correspond from OVS to `$FAKEINT`
 1. RECORD - 0 to not store pcaps passing through `$COPROINT`, anything else to store them
 1. PCAP_LOCATION - filename of store pcaps
 1. PIPETTE_TEMP_DIR temp directory to store process info
Most of the above can can be overridden by passing appropriate flags to the startup script. For more details run `./runpipette.sh --help` for more details

### Starting Pipette
1. Run the Shell script using `./runpipette.sh`. By default this will run Pipette in a docker container, use the `--no-docker` option to run it natively.  
1. Start any coprocessing services. It is important to ensure that the services are bound to one of the IPs containted in `$NFVIPS`. If using Docker besure to start the container using the `-p <IP>:<PORT>:<PORT>` option
