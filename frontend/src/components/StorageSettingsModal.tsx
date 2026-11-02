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
    let isMounted = true
    if (open) {
      setLoading(true)
      api.getSystemStorageStatus()
        .then((res) => {
          if (isMounted) setData(res)
        })
        .catch((err) => {
          console.error(err)
        })
        .finally(() => {
          if (isMounted) setLoading(false)
        })
    }
    return () => {
      isMounted = false
    }
  }, [open])

  const task = data?.scheduled_task || {}
  const stats = data?.stats || {}

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-100">
          <Settings className="w-4 h-4 text-slate-400" />
          <span>系統設定與資料存放管理</span>
        </div>
      }
      description="本機數據持久化目錄、磁碟佔用分析與 Windows 定時任務狀態"
      className="max-w-2xl max-h-[85vh] overflow-y-auto"
    >
      <div className="space-y-4 text-xs pt-1">
        {loading ? (
          <div className="p-8 text-center text-slate-500">正在檢查系統存放路徑與排程狀態...</div>
        ) : (
          <>
            {/* Storage Root */}
            <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-medium text-xs sm:text-sm text-slate-900 dark:text-slate-100 flex items-center gap-2">
                  <HardDrive className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                  本機資料儲存庫目錄
                </span>
                <Badge variant="secondary" className="font-mono text-[10px]">
                  {data?.storage_root_type || "Junction Link"}
                </Badge>
              </div>

              <div className="font-mono text-[11px] p-2 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 break-all select-all">
                {data?.storage_root || "c:\\Projects\\PythonProjects\\sportslottery\\data"}
              </div>

              {data?.target_path && (
                <div className="text-[11px] text-slate-500">
                  實體指向目標：<span className="font-mono text-slate-700 dark:text-slate-300">{data.target_path}</span>
                </div>
              )}

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-slate-200/80 dark:border-slate-800 text-[11px] font-mono">
                <div>
                  總檔案數：<span className="text-slate-700 dark:text-slate-300 tabular-nums">{stats?.total_files ?? 0} 個</span>
                </div>
                <div>
                  磁碟大小：<span className="text-slate-700 dark:text-slate-300 tabular-nums">{stats?.total_size_mb ?? "0"} MB</span>
                </div>
                <div>
                  權限狀態：<span className="text-emerald-600 dark:text-emerald-400 font-sans">正常可寫入</span>
                </div>
              </div>
            </div>

            {/* Scheduled Task */}
            <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-slate-200 dark:border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-medium text-xs sm:text-sm text-slate-900 dark:text-slate-100 flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-slate-400" />
                  Windows 排程任務 (台灣運彩每日快照)
                </span>
                <Badge variant={task?.exists ? "green" : "secondary"} className="text-[10px]">
                  {task?.exists ? "已建立" : "未註冊"}
                </Badge>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                <div>
                  任務名稱：<span className="text-slate-700 dark:text-slate-300">{task?.task_name || "MadDog_Taiwan_Sports_Sync"}</span>
                </div>
                <div>
                  執行週期：<span className="text-slate-700 dark:text-slate-300">{task?.schedule || "每日 09:00, 15:00"}</span>
                </div>
                <div>
                  上次執行：<span className="text-slate-700 dark:text-slate-300">{task?.last_run_time || "未執行"}</span>
                </div>
                <div>
                  上次結果：<span className="text-slate-700 dark:text-slate-300">{task?.last_result || "N/A"}</span>
                </div>
              </div>

              <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-500/20 text-emerald-800 dark:text-emerald-300 text-[11px] flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                <span>排程確保每日開盤第一時間快照賠率與籌碼分歧數據。</span>
              </div>
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
