import os
import math
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Credentials from gis-bk/.env
GEONODE_DB_USER = os.getenv("GEONODE_DATABASE_USER", "geonode_data")
GEONODE_DB_PASS = os.getenv("GEONODE_DATABASE_PASSWORD", "30183e8aab740342ab094c7350959fa6")
GEONODE_DB_HOST = os.getenv("GEONODE_DATABASE_HOST", "db4backend-geonode")
GEONODE_DB_PORT = os.getenv("GEONODE_DATABASE_PORT", "5432")
GEONODE_DB_NAME = os.getenv("GEONODE_GEODATABASE", "geonode_data")

GEONODE_DATABASE_URL = f"postgresql+psycopg2://{GEONODE_DB_USER}:{GEONODE_DB_PASS}@{GEONODE_DB_HOST}:{GEONODE_DB_PORT}/{GEONODE_DB_NAME}"

engine_geonode = create_engine(GEONODE_DATABASE_URL, pool_pre_ping=True)
SessionGeonode = sessionmaker(bind=engine_geonode)

def calculate_projection(lat: float, lon: float, sog_knots: float, cog_deg: float, minutes: int, buffer_meters: int = 300, traffic_type: str = None, dest_lat: float = None, dest_lon: float = None):
    """
    Calculates smooth projected path using Potential Fields Pathfinding.
    
    Forces:
    1. Inertia (Current Heading): 70% weight
    2. Attraction (Destination): 30% weight (if destination exists)
    3. Repulsion (Coastline): Overrides all if collision detected (20 deg turn)
    
    Args:
        lat, lon: Current position
        sog_knots: Speed over ground in knots
        cog_deg: Course over ground in degrees
        minutes: Projection time in minutes
        buffer_meters: Buffer distance from coastline
        traffic_type: Vessel traffic type
        dest_lat, dest_lon: Optional destination coordinates
        
    Returns:
        JSON string with inside/outside maritime geometries
    """
    if sog_knots is None or sog_knots < 0.1:
        return None
    
    speed_mps = sog_knots * 0.514444
    total_distance = speed_mps * minutes * 60
    
    # Optimized step size
    step_size = 2000 
    max_steps = int(total_distance / step_size)
    
    if max_steps > 150:
        step_size = total_distance / 150
        max_steps = 150

    sql = text("""
    WITH RECURSIVE 
    -- 1. Pre-calculate AOI
    aoi_buffer AS MATERIALIZED (
        SELECT ST_Union(ST_Buffer(ST_MakeValid(ST_Simplify(c.geometry, 0.001))::geography, :buffer)::geometry) as geom
        FROM linea_de_costa_ecuadorcontinental c
        WHERE ST_DWithin(
            c.geometry::geography, 
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 
            :total_distance + 5000
        )
    ),
    aoi_maritime AS MATERIALIZED (
        SELECT ST_Union(ST_MakeValid(ST_Simplify(m.geometry, 0.001))) as geom
        FROM espacios_maritimos_2021 m
        WHERE ST_DWithin(
            m.geometry::geography, 
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 
            :total_distance + 5000
        )
    ),
    -- Destination Point (if exists)
    dest_pt AS (
        SELECT CASE 
            WHEN :dest_lat IS NOT NULL THEN ST_SetSRID(ST_MakePoint(:dest_lon, :dest_lat), 4326)::geography 
            ELSE NULL 
        END as geom
    ),
    -- 2. Recursive path generation with Potential Fields
    path_steps(step, geom, current_cog) AS (
        -- Initial State
        SELECT 
            0 as step,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) as geom,
            CAST(:cog AS float) as current_cog
        
        UNION ALL
        
        -- Recursive Step
        SELECT 
            ps.step + 1,
            next_pt.geom,
            next_pt.new_cog
        FROM path_steps ps,
        LATERAL (
            -- Calculate Attraction Heading (to Destination)
            SELECT CASE 
                WHEN (SELECT geom FROM dest_pt) IS NOT NULL THEN 
                    degrees(ST_Azimuth(ps.geom::geography, (SELECT geom FROM dest_pt)))
                ELSE ps.current_cog
            END as dest_heading
        ) as attraction,
        LATERAL (
            -- Calculate Ideal Heading (Inertia + Attraction)
            SELECT CASE 
                WHEN (SELECT geom FROM dest_pt) IS NOT NULL THEN
                    degrees(atan2(
                        0.7 * sin(radians(ps.current_cog)) + 0.3 * sin(radians(attraction.dest_heading)),
                        0.7 * cos(radians(ps.current_cog)) + 0.3 * cos(radians(attraction.dest_heading))
                    ))
                ELSE ps.current_cog
            END as ideal_cog
        ) as heading,
        LATERAL (
            -- PROBE CANDIDATES: Generate points for BIDIRECTIONAL turn angles
            -- Tests both left (-) and right (+) to handle coastlines on either side
            SELECT 
                ST_Project(ps.geom::geography, :step_size, radians(heading.ideal_cog))::geometry as pt_ideal,
                ST_Project(ps.geom::geography, :step_size, radians(ps.current_cog + 20))::geometry as pt_right_1,
                ST_Project(ps.geom::geography, :step_size, radians(ps.current_cog - 20))::geometry as pt_left_1,
                ST_Project(ps.geom::geography, :step_size, radians(ps.current_cog + 45))::geometry as pt_right_2,
                ST_Project(ps.geom::geography, :step_size, radians(ps.current_cog - 45))::geometry as pt_left_2,
                ST_Project(ps.geom::geography, :step_size, radians(ps.current_cog + 90))::geometry as pt_right_3,
                ST_Project(ps.geom::geography, :step_size, radians(ps.current_cog - 90))::geometry as pt_left_3
        ) as probes,
        LATERAL (
            -- SELECT BEST PATH (Bidirectional)
            -- Check collision for each probe in order. Pick the first one that is clear.
            SELECT 
                CASE 
                    -- Try Ideal
                    WHEN (SELECT geom FROM aoi_buffer) IS NULL OR 
                         NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_ideal), (SELECT geom FROM aoi_buffer)) 
                    THEN probes.pt_ideal
                    
                    -- Try Right Soft (+20)
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_right_1), (SELECT geom FROM aoi_buffer)) 
                    THEN probes.pt_right_1
                    
                    -- Try Left Soft (-20)
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_left_1), (SELECT geom FROM aoi_buffer)) 
                    THEN probes.pt_left_1
                    
                    -- Try Right Hard (+45)
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_right_2), (SELECT geom FROM aoi_buffer)) 
                    THEN probes.pt_right_2
                    
                    -- Try Left Hard (-45)
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_left_2), (SELECT geom FROM aoi_buffer)) 
                    THEN probes.pt_left_2
                    
                    -- Try Right Emergency (+90)
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_right_3), (SELECT geom FROM aoi_buffer)) 
                    THEN probes.pt_right_3
                    
                    -- Default to Left Emergency (-90)
                    ELSE probes.pt_left_3
                END as geom,
                
                CASE 
                    -- Update Heading based on which point was chosen
                    WHEN (SELECT geom FROM aoi_buffer) IS NULL OR 
                         NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_ideal), (SELECT geom FROM aoi_buffer)) 
                    THEN heading.ideal_cog
                    
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_right_1), (SELECT geom FROM aoi_buffer)) 
                    THEN ps.current_cog + 20
                    
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_left_1), (SELECT geom FROM aoi_buffer)) 
                    THEN ps.current_cog - 20
                    
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_right_2), (SELECT geom FROM aoi_buffer)) 
                    THEN ps.current_cog + 45
                    
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_left_2), (SELECT geom FROM aoi_buffer)) 
                    THEN ps.current_cog - 45
                    
                    WHEN NOT ST_Intersects(ST_MakeLine(ps.geom::geometry, probes.pt_right_3), (SELECT geom FROM aoi_buffer)) 
                    THEN ps.current_cog + 90
                    
                    ELSE ps.current_cog - 90
                END as new_cog
        ) as next_pt
        WHERE ps.step < :max_steps
        AND (
            (SELECT geom FROM dest_pt) IS NULL 
            OR NOT ST_DWithin(ps.geom::geography, (SELECT geom FROM dest_pt), 3000)
        )
    ),
    -- 3. Build LineString
    smooth_path AS (
        SELECT ST_MakeLine(geom ORDER BY step) as geom
        FROM path_steps
    ),
    -- 4. Split into Inside/Outside
    final_lines AS (
        SELECT 
            CASE WHEN (SELECT geom FROM aoi_maritime) IS NOT NULL THEN
                ST_Intersection(sp.geom, (SELECT geom FROM aoi_maritime))
            ELSE NULL END as inside_geom,
            
            CASE WHEN (SELECT geom FROM aoi_maritime) IS NOT NULL THEN
                ST_Difference(sp.geom, (SELECT geom FROM aoi_maritime))
            ELSE NULL END as outside_geom
        FROM smooth_path sp
    )
    SELECT json_build_object(
        'inside', ST_AsGeoJSON(inside_geom),
        'outside', ST_AsGeoJSON(outside_geom),
        'traffic_type', :traffic_type
    )::text as result
    FROM final_lines;
    """)
    
    try:
        with engine_geonode.connect() as conn:
            result = conn.execute(sql, {
                "lon": lon, "lat": lat, 
                "total_distance": total_distance,
                "step_size": step_size,
                "max_steps": max_steps,
                "cog": cog_deg, 
                "buffer": buffer_meters,
                "traffic_type": traffic_type or "Nacional",
                "dest_lat": dest_lat,
                "dest_lon": dest_lon
            }).fetchone()
            
            if result and result[0]:
                return result[0]
    except Exception as e:
        print(f"Error in calculate_projection: {e}")
        return None
    return None
