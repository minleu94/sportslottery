import React from "react"
import { Dialog } from "@/components/ui/Dialog"
import { Badge } from "@/components/ui/Badge"
import { BookOpen, ShieldAlert, Sparkles, TrendingUp, Users, Scale } from "lucide-react"

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
        <div className="flex items-center gap-2 text-lg font-black text-white">
          <BookOpen className="w-5 h-5 text-emerald-400" />
          <span>📊 台灣運彩瘋狗流指標與資料來源說明</span>
        </div>
      }
      description="深入了解期望值 (+EV)、打平門檻與三大外部情報源評估邏輯"
      className="max-w-2xl max-h-[85vh] overflow-y-auto"
    >
      <div className="space-y-4 text-xs leading-relaxed text-slate-300 pt-2">
        {/* Section 1 */}
        <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2">
          <div className="flex items-center gap-2 font-bold text-sm text-emerald-400">
            <TrendingUp className="w-4 h-4" />
            期望值 (+EV: Expected Value) 與打平門檻
          </div>
          <p>
            <b>賠率決定派彩，1 ÷ 賠率是打平門檻。</b> 舉例：賠率 1.80 之打平門檻為 55.6%，若綜合模型預測真實勝率大於 55.6%，即產生正期望值 (+EV)。
          </p>
          <div className="flex items-center gap-2 pt-1">
            <Badge variant="green" className="text-[10px]">+EV 正期望值</Badge>
            <span className="text-slate-400">長期投注具有數學優勢之精選關卡。</span>
          </div>
        </div>

        {/* Section 2 */}
        <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2">
          <div className="flex items-center gap-2 font-bold text-sm text-sky-400">
            <Users className="w-4 h-4" />
            三大訊號情報源 (Signal Hub)
          </div>
          <ul className="list-disc list-inside space-y-1.5 pl-1">
            <li>
              <b>大神歷史勝率 (Expert Picks)</b>：玩運彩賽事推薦大神歷史勝率 &gt; 58% 之高勝率推介。
            </li>
            <li>
              <b>大眾投票共識 (Crowd Consensus)</b>：全網彩迷投票支持率 &gt; 65% 之強勢熱度指標。
            </li>
            <li>
              <b>開源預測模型 (ML/Elo Models)</b>：MLB Elo、籃球泊松/進階戰力模型之真實勝率評估。
            </li>
          </ul>
        </div>

        {/* Section 3 */}
        <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2">
          <div className="flex items-center gap-2 font-bold text-sm text-amber-400">
            <ShieldAlert className="w-4 h-4" />
            盤口異動預警：跳水與升水誘盤 (Line Movements)
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
            <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <span className="font-bold text-emerald-300">📉 跳水 (Steam Move)</span>
              <p className="mt-1 text-slate-300">賠率急速下調，代表主力資金狂湧，系統優先順應推薦。</p>
            </div>
            <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <span className="font-bold text-amber-300">⚠️ 升水誘盤 (Trap Move)</span>
              <p className="mt-1 text-slate-300">支持度極高但莊家逆勢調升賠率誘誘受熱，系統發出避險預警。</p>
            </div>
          </div>
        </div>

        {/* Section 4 */}
        <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2">
          <div className="flex items-center gap-2 font-bold text-sm text-purple-400">
            <Scale className="w-4 h-4" />
            每週健康娛樂預算與儲備池架構
          </div>
          <p>
            嚴格執行「每週娛樂預算上限」（預設 NT$ 200）。<b>中獎派彩全數撥入【保留儲備池】</b>，若儲備池充盈則下週無需外部自掏腰包補金，達成以戰養戰、零壓力健康娛樂！
          </p>
        </div>
      </div>
    </Dialog>
  )
}
