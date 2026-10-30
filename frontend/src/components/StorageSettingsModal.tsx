import React, { useState, useEffect } from "react"
import { Dialog } from "@/components/ui/Dialog"
import { Badge } from "@/components/ui/Badge"
import { api } from "@/services/api"
import { Settings, Calendar, HardDrive, ShieldCheck } from "lucide-react"

interface StorageSettingsModalProps {
  open: boolean
  onClose: () => void
}

export const StorageSettingsModal: React.FC<StorageSettingsModalProps> = ({ open, onClose }) => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState<boolean>(true)

  useEffect(() => {
    if (open) {
      loadStorage()
    }
  }, [open])

  async function loadStorage() {
    setLoading(true)
    try {
      const res = await api.getSystemStorageStatus()
      setData(res)
    } catch (err: any) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const task = data?.scheduled_task || {}
  const stats = data?.stats || {}

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2 text-lg font-black text-white">
          <Settings className="w-5 h-5 text-indigo-400" />
          <span>⚙️ 系統設定與資料存放管理 (管理員專屬)</span>
        </div>
      }
      description="本機數據持久化目錄、磁碟佔用分析與 Windows 定時任務狀態"
      className="max-w-2xl max-h-[85vh] overflow-y-auto"
    >
      <div className="space-y-4 text-xs pt-2">
        {loading ? (
          <div className="p-8 text-center text-slate-500">正在檢查系統存放路徑與排程狀態...</div>
        ) : (
          <>
            {/* Storage Root */}
            <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-white flex items-center gap-2">
                  <HardDrive className="w-4 h-4 text-emerald-400" />
                  本機資料儲存庫目錄 (Storage Root)
                </span>
                <Badge variant="green" className="text-[10px]">在線掛載</Badge>
              </div>
              <div className="p-2.5 rounded bg-slate-900 border border-slate-800/80 font-mono text-emerald-300 text-[11px] break-all">
                {data?.storage_root || "F:\\Min\\Python\\Project\\SportsLottery_Data"}
              </div>
              {stats && Object.keys(stats).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 font-mono text-[11px] text-slate-400">
                  <div>歷史快照：<b className="text-white">{stats.snapshot_count ?? "0"} 筆</b></div>
                  <div>注單檔案：<b className="text-white">{stats.ticket_count ?? "0"} 筆</b></div>
                  <div>模型權重：<b className="text-white">{stats.model_cache_size ?? "正常"}</b></div>
                  <div>目錄容量：<b className="text-white">{stats.total_disk_usage ?? "正常"}</b></div>
                </div>
              )}
            </div>

            {/* Windows Task Scheduler */}
            <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-bold text-sm text-white flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-sky-400" />
                  Windows 背景定時研究排程 (Task Scheduler)
                </span>
                <Badge variant={task.Enabled ? "green" : "secondary"} className="text-[10px]">
                  {task.Enabled ? "🟢 啟用運行中" : "已停用"}
                </Badge>
              </div>
              <p className="text-slate-400">
                系統排程定時自動蒐集盤口、大神勝率與進行前瞻研究管線回放評估。
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-[11px] text-slate-300 pt-1">
                <div>上次執行：<span className="text-slate-200">{task.LastRunTime || "無"}</span></div>
                <div>下次排定：<span className="text-slate-200">{task.NextRunTime || "無"}</span></div>
              </div>
            </div>

            {/* Security info */}
            <div className="p-3.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 flex items-center gap-2 text-[11px]">
              <ShieldCheck className="w-4 h-4 shrink-0" />
              <span>系統已開啟單一通訊埠 (Port 8000) 靜默守護進程，由系統匣托盤圖示原生監控。</span>
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
