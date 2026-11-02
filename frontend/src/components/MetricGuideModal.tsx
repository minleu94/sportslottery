import React from "react"
import { Dialog } from "@/components/ui/Dialog"
import { Badge } from "@/components/ui/Badge"
import { BookOpen, ShieldAlert, TrendingUp, Users, Scale, ArrowDown, ArrowUp } from "lucide-react"

interface MetricGuideModalProps {
  open: boolean
  onClose: () => void
}

export const MetricGuideModal: React.FC<MetricGuideModalProps> = ({ open, onClose }) => {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-100">
          <BookOpen className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          <span>運彩量化指標與資料來源說明</span>
        </div>
      }
      description="期望值 (+EV)、打平門檻與三大外部情報源評估邏輯"
      className="max-w-2xl max-h-[85vh] overflow-y-auto"
    >
      <div className="space-y-3.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300 pt-1">
        {/* Section 1 */}
        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 space-y-1.5">
          <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
            <TrendingUp className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            期望值 (+EV: Expected Value) 與打平門檻
          </div>
          <p>
            <b>賠率決定派彩，1 ÷ 賠率為打平門檻。</b> 舉例：賠率 1.80 之打平門檻為 55.6%，若綜合模型預測真實勝率大於 55.6%，即產生正期望值 (+EV)。
          </p>
          <div className="flex items-center gap-2 pt-1">
            <Badge variant="green" className="text-[10px]">+EV 正期望值</Badge>
            <span className="text-slate-500">長期投注具有數學優勢之精選關卡。</span>
          </div>
        </div>

        {/* Section 2 */}
        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 space-y-1.5">
          <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
            <Users className="w-4 h-4 text-slate-500" />
            三大訊號情報源 (Signal Hub)
          </div>
          <ul className="list-disc list-inside space-y-1 pl-1">
            <li>
              <b>專家歷史勝率 (Expert Picks)</b>：玩運彩賽事推薦大神歷史勝率 &gt; 58% 之高勝率推介。
            </li>
            <li>
              <b>大眾投票共識 (Crowd Consensus)</b>：全網彩迷投票支持率 &gt; 65% 之強勢熱度指標。
            </li>
            <li>
              <b>開源預測模型 (ML/Elo Models)</b>：MLB Elo、籃球進階戰力模型之真實勝率評估。
            </li>
          </ul>
        </div>

        {/* Section 3 */}
        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 space-y-1.5">
          <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
            <ShieldAlert className="w-4 h-4 text-slate-500" />
            盤口異動預警：跳水與升水誘盤 (Line Movements)
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] pt-1">
            <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-500/20">
              <span className="font-medium text-emerald-800 dark:text-emerald-300 flex items-center gap-1">
                <ArrowDown className="w-3 h-3" /> 跳水順勢 (Steam Move)
              </span>
              <p className="mt-1 text-slate-600 dark:text-slate-400">賠率急速下調，代表主力資金狂湧，系統優先順應推薦。</p>
            </div>
            <div className="p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-500/20">
              <span className="font-medium text-amber-800 dark:text-amber-300 flex items-center gap-1">
                <ArrowUp className="w-3 h-3" /> 升水誘盤 (Trap Move)
              </span>
              <p className="mt-1 text-slate-600 dark:text-slate-400">支持度極高但莊家逆勢調升賠率誘受熱，系統發出避險預警。</p>
            </div>
          </div>
        </div>

        {/* Section 4 */}
        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-950/50 border border-slate-200 dark:border-slate-800 space-y-1.5">
          <div className="flex items-center gap-2 font-medium text-sm text-slate-900 dark:text-slate-100">
            <Scale className="w-4 h-4 text-slate-500" />
            每週健康娛樂預算與儲備池架構
          </div>
          <p>
            嚴格執行「每週娛樂預算上限」（預設 NT$ 200）。<b>中獎派彩全數撥入【獲利儲備池】</b>，若儲備池充盈則下週無需外部自掏腰包補金，達成零壓力理性娛樂。
          </p>
        </div>
      </div>
    </Dialog>
  )
}
