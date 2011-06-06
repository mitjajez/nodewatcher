from web.registry.cgm import base as cgm_base
from web.registry.cgm import routers as cgm_routers
from web.registry.cgm import protocols as cgm_protocols

class Fonera(cgm_routers.RouterBase):
  """
  Fonera FON-2100 device descriptor.
  """
  identifier = "fon-2100"
  name = "Fonera"
  manufacturer = "Fon Wireless Ltd."
  url = "http://www.fon.com"
  architecture = "atheros"
  radios = [
    cgm_routers.IntegratedRadio("ath0", "Wifi0", [cgm_protocols.IEEE80211BG])
  ]
  ports = [
    cgm_routers.EthernetPort("eth0", "Ethernet0")
  ]
  antennas = [
    cgm_routers.InternalAntenna(
      identifier = "a1",
      polarization = "horizontal",
      angle_horizontal = 360,
      angle_vertical = 75,
      gain = 2
    )
  ]
  
  @cgm_routers.register_module()
  def network(node, cfg):
    """
    Network configuration CGM for FON-2100.
    """
    pass

# Register the FON-2100 router
cgm_base.register_router("openwrt", Fonera)

