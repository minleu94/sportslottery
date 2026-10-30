import React, { useState, useEffect } from "react"
import { Dialog } from "@/components/ui/Dialog"
import { Badge } from "@/components/ui/Badge"
import { api } from "@/services/api"
import { Activity, Server, RefreshCw } from "lucide-react"

interface SystemHealthModalProps {
  open: boolean
  onClose: () => void
}

export const SystemHealthModal: React.FC<SystemHealthModalProps> = ({ open, onClose }) => {
  const [sourceStatus, setSourceStatus] = useState<any>(null)
  const [loading, setLoading] = useState<boolean>(true)

  useEffect(() => {
    if (open) {
      loadHealth()
    }
  }, [open])

  async function loadHealth() {
    setLoading(true)
    try {
      const res = await api.getRadar(false)
      setSourceStatus(res.source_status || {})
    } catch (err: any) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const allianceNames: Record<string, string> = {
    "1": "NBA (美國職籃)",
    "2": "WNBA (女子職籃)",
    "3": "MLB (美國職棒)",
    "4": "國際足球 (綜合聯賽)",
    "6": "CPBL (中華職棒)",
    "7": "NPB (日本職棒)",
    "8": "KBO (韓國職棒)",
    "9": "NFL (美式足球)",
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center justify-between w-full pr-4">
          <div className="flex items-center gap-2 text-lg font-black text-white">
            <Activity className="w-5 h-5 text-emerald-400" />
            <span>🔎 資料來源健康度與爬蟲觀測</span>
          </div>
          <button
            onClick={loadHealth}
            disabled={loading}
            className="p-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors cursor-pointer"
            title="重新探測"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      }
      description="監控玩運彩盤口、大神榜與模型伺服器之快取存活時間 (TTL) 與資料完整度"
      className="max-w-2xl max-h-[85vh] overflow-y-auto"
    >
      <div className="space-y-3 text-xs pt-2">
        {loading ? (
          <div className="p-8 text-center text-slate-500">正在探測資料來源狀態...</div>
        ) : !sourceStatus || Object.keys(sourceStatus).length === 0 ? (
          <div className="p-8 text-center text-slate-500">暫無資料來源觀測紀錄</div>
        ) : (
          <div className="space-y-2">
            {Object.entries(sourceStatus).map(([aid, info]: [string, any]) => {
              const name = allianceNames[aid] || `聯盟 #${aid}`
              const rawStatus = info.source_status || "UNKNOWN"
              const isFresh = rawStatus === "CACHED" || rawStatus === "LIVE"
              const age = typeof info.cache_age_minutes === "number" ? `${info.cache_age_minutes.toFixed(1)} 分鐘` : "即時"

              return (
                <div key={aid} className="p-3 rounded-xl bg-slate-950/80 border border-slate-800/80 flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white text-sm flex items-center gap-1.5">
                      <Server className="w-4 h-4 text-slate-500" />
                      {name}
                    </span>
                    <Badge variant={isFresh ? "green" : "secondary"} className="text-[10px]">
                      {isFresh ? "🟢 正常運作" : rawStatus}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[11px] text-slate-400 mt-1 font-mono">
                    <div>
                      盤口賽事數：<span className="text-slate-200">{info.market_match_count ?? 0} 場</span>
                    </div>
                    <div>
                      快取年齡：<span className="text-slate-200">{age}</span>
                    </div>
                    <div>
                      最後觀測：<span className="text-slate-200">{info.observed_at ? info.observed_at.slice(11, 19) : "N/A"}</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Dialog>
  )
}
