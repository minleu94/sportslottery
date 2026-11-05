import type { Leg, LegsResponse, RadarLeague, RadarResponse } from "@/types"

export interface RadarSnapshot {
  cachedAt: number
  leagues: RadarLeague[]
  legs: Leg[]
}

export interface RadarSnapshotApi {
  getRadar(forceRefresh?: boolean): Promise<RadarResponse>
  getLegs(alliances?: string[], forceRefresh?: boolean): Promise<LegsResponse>
}

const RADAR_CACHE_TTL_MS = 3 * 60 * 1000
let radarSnapshot: RadarSnapshot | null = null
let inFlightRequest: { forceRefresh: boolean; promise: Promise<RadarSnapshot> } | null = null
const listeners = new Set<() => void>()

export function getCachedRadarSnapshot(): RadarSnapshot | null {
  return radarSnapshot
}

export function subscribeRadarSnapshot(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function isRadarSnapshotFresh(snapshot: RadarSnapshot | null, now = Date.now()): snapshot is RadarSnapshot {
  return Boolean(snapshot && now - snapshot.cachedAt < RADAR_CACHE_TTL_MS)
}

export async function loadRadarSnapshot(api: RadarSnapshotApi, forceRefresh = false): Promise<RadarSnapshot> {
  if (!forceRefresh && isRadarSnapshotFresh(radarSnapshot)) {
    return radarSnapshot
  }

  if (inFlightRequest) {
    const activeRequest = inFlightRequest
    if (!forceRefresh || activeRequest.forceRefresh) {
      return activeRequest.promise
    }

    // A forced refresh arriving during an initial load runs once after it, so
    // the explicit refresh still bypasses the server cache without duplicate
    // concurrent calls.
    await activeRequest.promise.catch(() => undefined)
    return loadRadarSnapshot(api, true)
  }

  const promise = (async () => {
    const radarData = await api.getRadar(forceRefresh)
    // /radar refreshes the source cache. Read /legs afterward without forcing
    // another source refresh for every league.
    const legsData = await api.getLegs()
    const snapshot: RadarSnapshot = {
      cachedAt: Date.now(),
      leagues: radarData.radar || [],
      legs: legsData.legs || [],
    }
    radarSnapshot = snapshot
    listeners.forEach((listener) => listener())
    return snapshot
  })()
  const request = { forceRefresh, promise }
  inFlightRequest = request

  try {
    return await promise
  } finally {
    if (inFlightRequest === request) {
      inFlightRequest = null
    }
  }
}
