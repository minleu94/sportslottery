import React, { useState, useEffect } from "react"
import { api } from "@/services/api"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { Badge } from "@/components/ui/Badge"
import { Skeleton } from "@/components/ui/Skeleton"
import { BarChart2, ShieldCheck, Users, Brain, TrendingUp } from "lucide-react"

export const ResearchView: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadAnalytics()
  }, [])

  async function loadAnalytics() {
    setLoading(true)
    try {
      const res = await api.getResearchAnalytics()
      setData(res)
    } catch (err: any) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  const portfolio = data?.shadow_portfolio || {}

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-black text-slate-100 flex items-center gap-2">
          <BarChart2 className="w-5 h-5 text-emerald-400" />
          影子前瞻評估與模型指標 (Shadow Forward Evaluation)
        </h2>
        <p className="text-sm text-slate-400 mt-0.5">
          追蹤前瞻快照、真實賽果回測、大眾共識與專家主推的校準表現
        </p>
      </div>

      {/* Snapshot Stats Header Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/80">
          <div className="text-xs text-slate-400">歷史盤口快照總數</div>
          <div className="text-2xl font-black text-emerald-400 font-mono mt-1">
            {data?.total_snapshots?.toLocaleString() || 0}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">獨立觀測樣本</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/80">
          <div className="text-xs text-slate-400">影子投組勝率</div>
          <div className="text-2xl font-black text-amber-400 font-mono mt-1">
            {((portfolio?.win_rate || 0) * 100).toFixed(1)}%
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {portfolio?.total_tickets || 0} 筆影子模擬單
          </div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/80">
          <div className="text-xs text-slate-400">影子投組 ROI</div>
          <div className="text-2xl font-black text-sky-400 font-mono mt-1">
            {portfolio?.roi ? `${(portfolio.roi * 100).toFixed(1)}%` : "0.0%"}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">虛擬回測收益率</div>
        </div>

        <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/80">
          <div className="text-xs text-slate-400">前瞻族群追蹤</div>
          <div className="text-2xl font-black text-purple-400 font-mono mt-1">
            {data?.cohort?.resolved_count || 0}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">已結算校準樣本</div>
        </div>
      </div>

      {/* Research Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Consensus & Crowd breakdown */}
        <Card className="border-slate-800 bg-slate-900/80">
          <CardHeader className="pb-3 border-b border-slate-800/80">
            <CardTitle className="text-base flex items-center gap-2">
              <Users className="w-4 h-4 text-sky-400" />
              社群大眾投票分組校準
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <p className="text-xs text-slate-400">
              分析玩運彩社群公眾投票不同比例（如 50%、60%、70%）在真實開獎中的勝率與 EV 偏差。
            </p>
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300">
              <div className="font-semibold text-emerald-400 mb-1">統計觀察重點：</div>
              <ul className="list-disc list-inside space-y-1 text-slate-400">
                <li>大眾選票 &gt; 70% 之熱門場次常具備降水效應。</li>
                <li>逆向升水（莊家受熱反而調高賠率）往往為高風險陷阱。</li>
              </ul>
            </div>
          </CardContent>
        </Card>

        {/* Model & Expert breakdown */}
        <Card className="border-slate-800 bg-slate-900/80">
          <CardHeader className="pb-3 border-b border-slate-800/80">
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="w-4 h-4 text-emerald-400" />
              統計模型與專家主推評估
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4 space-y-3">
            <p className="text-xs text-slate-400">
              Poisson 分佈足球模型、MLB Elo 動態評分與玩運彩殺手大神榜首信號之交叉驗證。
            </p>
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300">
              <div className="font-semibold text-amber-400 mb-1">多來源獨立支持原則：</div>
              <p className="text-slate-400">
                當「大神推薦」、「大眾投票」與「模型估計」三者有 2 項以上同向支持時，串關成功率顯著提升。
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
