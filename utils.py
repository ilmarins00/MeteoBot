def extract_pressure_hpa(dati_device):
    """
    Estrae la pressione in hPa dalla risposta Tuya con fallback su più chiavi.
    """
    # Prova chiavi comuni
    for key in ["pressure", "pressure_hpa", "pressure_local", "pressure_station"]:
        val = dati_device.get(key)
        if val is not None:
            try:
                return float(val)
            except Exception:
                continue
    # Prova chiavi con conversione da decimi
    for key in ["pressure_value", "pressure_value_hpa"]:
        val = dati_device.get(key)
        if val is not None:
            try:
                return float(val) / 10.0
            except Exception:
                continue
    return None
