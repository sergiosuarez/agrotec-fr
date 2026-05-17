import os
import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Credentials from gis-bk/.env (reused from projection.py)
GEONODE_DB_USER = os.getenv("GEONODE_DATABASE_USER", "geonode_data")
GEONODE_DB_PASS = os.getenv("GEONODE_DATABASE_PASSWORD", "30183e8aab740342ab094c7350959fa6")
GEONODE_DB_HOST = os.getenv("GEONODE_DATABASE_HOST", "db4backend-geonode")
GEONODE_DB_PORT = os.getenv("GEONODE_DATABASE_PORT", "5432")
GEONODE_DB_NAME = os.getenv("GEONODE_GEODATABASE", "geonode_data")

GEONODE_DATABASE_URL = f"postgresql+psycopg2://{GEONODE_DB_USER}:{GEONODE_DB_PASS}@{GEONODE_DB_HOST}:{GEONODE_DB_PORT}/{GEONODE_DB_NAME}"

engine_geonode = create_engine(GEONODE_DATABASE_URL, pool_pre_ping=True)

def check_spatial_status(lat: float, lon: float, mmsi: int, traffic_type: str = None):
    """
    Checks if the vessel is in a restricted zone or outside maritime spaces.
    
    Args:
        lat: Latitude
        lon: Longitude
        mmsi: Vessel MMSI
        traffic_type: 'Internacional' or other.
        
    Returns:
        dict: { "alert": bool, "color": str, "reason": str }
    """
    
    # Default status
    status = {"alert": False, "color": "green", "reason": None}
    
    # 1. Check Restricted Zones (zonas_restringidas)
    # If inside -> Alert Orange
    sql_restricted = text("""
        SELECT 1 
        FROM zonas_restringidas 
        WHERE ST_Intersects(the_geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        LIMIT 1
    """)
    
    # 2. Check Maritime Spaces (espacios_maritimos_2021)
    # If outside -> Alert Orange (unless International)
    sql_maritime = text("""
        SELECT 1 
        FROM espacios_maritimos_2021 
        WHERE ST_Intersects(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        LIMIT 1
    """)
    
    try:
        with engine_geonode.connect() as conn:
            # Check Restricted
            is_restricted = conn.execute(sql_restricted, {"lon": lon, "lat": lat}).scalar()
            if is_restricted:
                return {"alert": True, "color": "orange", "reason": "Zona Restringida"}
            
            # Check Maritime Space
            is_in_maritime = conn.execute(sql_maritime, {"lon": lon, "lat": lat}).scalar()
            print(f"DEBUG: is_in_maritime: {is_in_maritime} for {lat}, {lon}")
            
            if not is_in_maritime:
                print(f"DEBUG: Traffic type: {traffic_type}")
                if traffic_type and traffic_type.lower() == "internacional":
                    pass # Allowed
                else:
                    return {"alert": True, "color": "orange", "reason": "Fuera de Espacio Marítimo"}
                    
    except Exception as e:
        print(f"Error in spatial checks: {e}")
        # Fail safe: return green if DB error? Or keep previous?
        # For now, return green to avoid panic
        return status
        
    return status
