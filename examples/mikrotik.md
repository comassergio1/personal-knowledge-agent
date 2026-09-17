# Configuración de VLANs en MikroTik RB5009

## WAN

El WAN del RB5009 está configurado en **ether8**.

## VLANs

- **VLAN 10** → LAN principal
- **VLAN 30** → IoT
- **VLAN 50** → Invitados

## Pasos

1. Crear las interfaces VLAN: `/interface vlan add name=VLAN10 vlan-id=10 interface=bridge-local`
2. Asignar direcciones IP por VLAN.
3. Agregar reglas de firewall para aislar IoT del resto.

## OpenWrt como AP

Para configurar OpenWrt como access point:
1. Conectar por cable al puerto LAN del AP.
2. Configurar IP estática en el mismo rango que la LAN.
3. Deshabilitar DHCP en el AP y usar la IP del router como gateway.