import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { Profile } from "@/types"
import { formatNTD } from "@/lib/utils"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { User, KeyRound, Shield, CheckCircle2, AlertCircle, Users, Crown, Eye, UserPlus, RefreshCw } from "lucide-react"

interface ProfileViewProps {
  currentProfile: Profile | null
  onProfileChange: (profile: Profile) => void
}

interface PlayerOverviewItem {
  id: string
  name: string
  weekly_play_cap: number
  weekly_wallet_balance: number
  weekly_staked: number
  prize_pool: number
  lifetime_net_profit: number
  is_line_bound: boolean
  created_at: string
  active_tickets_count: number
  total_tickets_count: number
}

export const ProfileView: React.FC<ProfileViewProps> = ({ currentProfile, onProfileChange }) => {
  const isAdmin = currentProfile?.name === "Archie" || currentProfile?.id === "default"
  const [activeTab, setActiveTab] = useState<"edit" | "admin_overview" | "create">("edit")

  const [profiles, setProfiles] = useState<Profile[]>([])
  const [selectedProfileId, setSelectedProfileId] = useState<string>(currentProfile?.id || "default")
  const [pinCode, setPinCode] = useState<string>("")
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null)

  // Edit settings
  const [editName, setEditName] = useState<string>(currentProfile?.name || "")
  const [editCap, setEditCap] = useState<number>(currentProfile?.weekly_play_cap || 200)
  const [currentPinForEdit, setCurrentPinForEdit] = useState<string>("")
  const [newPin, setNewPin] = useState<string>("")

  // Admin Overview
  const [adminPlayers, setAdminPlayers] = useState<PlayerOverviewItem[]>([])
  const [loadingAdmin, setLoadingAdmin] = useState(false)

  // Create Profile Form
  const [newName, setNewName] = useState("")
  const [newCap, setNewCap] = useState(200)
  const [createPin, setCreatePin] = useState("0000")

  useEffect(() => {
    loadProfiles()
    if (isAdmin) {
      loadAdminPlayers()
    }
  }, [currentProfile])

  useEffect(() => {
    if (currentProfile) {
      setSelectedProfileId(currentProfile.id)
      setEditName(currentProfile.name)
      setEditCap(currentProfile.weekly_play_cap)
    }
  }, [currentProfile])

  async function loadProfiles() {
    try {
      const res = await api.getProfiles()
      setProfiles(res.profiles || [])
    } catch (err: any) {
      console.error(err)
    }
  }

  async function loadAdminPlayers() {
    setLoadingAdmin(true)
    try {
      const res = await api.getAdminPlayersOverview(currentProfile?.id || "default")
      setAdminPlayers(res.players || [])
    } catch (err: any) {
      console.error("載入全體玩家失敗:", err)
    } finally {
      setLoadingAdmin(false)
    }
  }

  async function handleSwitchProfile() {
    if (!pinCode) {
      setMessage({ type: "error", text: "請輸入 4 位數 PIN 碼（預設為 0000）" })
      return
    }
    setLoading(true)
    setMessage(null)

    try {
      const res = await api.verifyPin(selectedProfileId, pinCode)
      onProfileChange(res.profile)
      setMessage({ type: "success", text: `已成功切換為【${res.profile.name}】身分！` })
      setPinCode("")
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "PIN 碼錯誤" })
    } finally {
      setLoading(false)
    }
  }

  async function handleAdminDirectSwitch(player: PlayerOverviewItem) {
    // Admin directly switches perspective to inspect that player
    const prof: Profile = {
      id: player.id,
      name: player.name,
      weekly_play_cap: player.weekly_play_cap,
      created_at: player.created_at,
    }
    onProfileChange(prof)
    setMessage({ type: "success", text: `👑 管理員特權：已切換至【${player.name}】視角！` })
  }

  async function handleSaveSettings() {
    if (!currentPinForEdit) {
      setMessage({ type: "error", text: "修改設定需輸入目前 PIN 碼進行身分驗證。" })
      return
    }
    setLoading(true)
    setMessage(null)

    try {
      const res = await api.updateProfile({
        profile_id: currentProfile?.id || "default",
        current_pin: currentPinForEdit,
        name: editName,
        weekly_play_cap: editCap,
        new_pin: newPin || undefined,
      })
      onProfileChange(res.profile)
      setMessage({ type: "success", text: "個人設定已成功更新！" })
      setCurrentPinForEdit("")
      setNewPin("")
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "更新失敗" })
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateProfile(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) {
      setMessage({ type: "error", text: "請輸入玩家姓名。" })
      return
    }
    setLoading(true)
    setMessage(null)
    try {
      const res = await api.registerProfile(newName.trim(), newCap, createPin)
      setMessage({ type: "success", text: `已成功建立新玩家【${res.profile.name}】！` })
      setNewName("")
      setNewCap(200)
      setCreatePin("0000")
      await loadProfiles()
      if (isAdmin) await loadAdminPlayers()
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "建立玩家失敗" })
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="max-w-4xl mx-auto space-y-6"
    >
      <div>
        <h2 className="text-xl font-black text-slate-900 dark:text-slate-100 flex items-center gap-2">
          <User className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
          個人設定與風控管理 (Player Profile & Governance)
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          獨立錢包帳本、PIN 碼隱私防護與多玩家健康娛樂額度管理
        </p>
      </div>

      {message && (
        <div
          className={`p-4 rounded-xl text-sm flex items-center gap-2 ${
            message.type === "success"
              ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
              : "bg-rose-500/10 border border-rose-500/30 text-rose-700 dark:text-rose-300"
          }`}
        >
          {message.type === "success" ? <CheckCircle2 className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
          <span>{message.text}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-800 gap-2 pb-2">
        <button
          onClick={() => setActiveTab("edit")}
          className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
            activeTab === "edit"
              ? "bg-emerald-600/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/40"
              : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          }`}
        >
          <User className="w-3.5 h-3.5" />
          <span>⚙️ 編輯個人設定</span>
        </button>

        {isAdmin && (
          <button
            onClick={() => {
              setActiveTab("admin_overview")
              loadAdminPlayers()
            }}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
              activeTab === "admin_overview"
                ? "bg-amber-600/20 text-amber-600 dark:text-amber-400 border border-amber-500/40"
                : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            }`}
          >
            <Crown className="w-3.5 h-3.5 text-amber-400" />
            <span>👑 全體玩家監控與切換 (管理員)</span>
          </button>
        )}

        <button
          onClick={() => setActiveTab("create")}
          className={`px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${
            activeTab === "create"
              ? "bg-purple-600/20 text-purple-600 dark:text-purple-400 border border-purple-500/40"
              : "bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          }`}
        >
          <UserPlus className="w-3.5 h-3.5" />
          <span>➕ 新增玩家 Profile</span>
        </button>
      </div>

      {/* TAB 1: EDIT SETTINGS */}
      {activeTab === "edit" && (
        <div className="space-y-6">
          {/* Switch Profile Card */}
          <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
            <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
              <CardTitle className="text-base flex items-center gap-2">
                <Shield className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                切換帳號身分
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">選擇帳號</label>
                <select
                  value={selectedProfileId}
                  onChange={(e) => setSelectedProfileId(e.target.value)}
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-800 dark:text-slate-200 cursor-pointer"
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} (每週上限: {formatNTD(p.weekly_play_cap)})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                  <KeyRound className="w-3.5 h-3.5 text-amber-500" />
                  輸入 4 位數 PIN 碼 (預設: 0000)
                </label>
                <input
                  type="password"
                  maxLength={4}
                  value={pinCode}
                  onChange={(e) => setPinCode(e.target.value)}
                  placeholder="••••"
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-center text-lg font-mono tracking-widest text-slate-900 dark:text-slate-100"
                />
              </div>

              <Button
                variant="default"
                onClick={handleSwitchProfile}
                disabled={loading}
                className="w-full font-bold cursor-pointer"
              >
                確認切換身分
              </Button>
            </CardContent>
          </Card>

          {/* Edit Profile Settings Card */}
          <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
            <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
              <CardTitle className="text-base flex items-center gap-2">
                <User className="w-4 h-4 text-sky-500" />
                修改目前帳號【{currentProfile?.name}】參數
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">顯示暱稱</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">每週最大損失風控上限 (NT$)</label>
                <input
                  type="number"
                  min={100}
                  max={5000}
                  step={50}
                  value={editCap}
                  onChange={(e) => setEditCap(Number(e.target.value))}
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-mono tabular-nums text-slate-900 dark:text-slate-200"
                />
                <p className="text-[11px] text-slate-500">
                  嚴格控制每週最多承受的外部補金總額，超出後必須等待下週自動重置。
                </p>
              </div>

              <div className="pt-2 border-t border-slate-200 dark:border-slate-800/80 space-y-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">變更新 PIN 碼 (留空則不變)</label>
                  <input
                    type="password"
                    maxLength={4}
                    value={newPin}
                    onChange={(e) => setNewPin(e.target.value)}
                    placeholder="4 位數新 PIN"
                    className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-mono text-slate-900 dark:text-slate-200"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-amber-600 dark:text-amber-400">輸入目前 PIN 碼驗證授權</label>
                  <input
                    type="password"
                    maxLength={4}
                    value={currentPinForEdit}
                    onChange={(e) => setCurrentPinForEdit(e.target.value)}
                    placeholder="目前 4 位 PIN"
                    className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-mono text-slate-900 dark:text-slate-200"
                  />
                </div>
              </div>

              <Button
                variant="success"
                onClick={handleSaveSettings}
                disabled={loading}
                className="w-full font-bold cursor-pointer"
              >
                儲存風控設定
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {/* TAB 2: ADMIN ALL PLAYERS OVERVIEW */}
      {isAdmin && activeTab === "admin_overview" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                <Crown className="w-4 h-4 text-amber-500" />
                全系統玩家資產監控與視角切換 (共 {adminPlayers.length} 位玩家)
              </h3>
              <p className="text-xs text-slate-500">
                僅管理員 Archie 可查閱全體玩家之預算額度、即時餘額、儲備池及進行 1 鍵視角切換。
              </p>
            </div>
            <button
              onClick={loadAdminPlayers}
              disabled={loadingAdmin}
              className="p-1.5 rounded-lg bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white transition-colors cursor-pointer"
            >
              <RefreshCw className={`w-4 h-4 ${loadingAdmin ? "animate-spin" : ""}`} />
            </button>
          </div>

          {loadingAdmin ? (
            <div className="p-8 text-center text-slate-500">載入全體玩家數據中...</div>
          ) : (
            <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 overflow-hidden shadow">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-100 dark:bg-slate-950/80 border-b border-slate-200 dark:border-slate-800 text-slate-500 font-mono">
                    <tr>
                      <th className="p-3">玩家名稱</th>
                      <th className="p-3">每週預算限額</th>
                      <th className="p-3">本週可用餘額</th>
                      <th className="p-3">保留儲備池</th>
                      <th className="p-3">歷史淨利</th>
                      <th className="p-3">LINE 綁定</th>
                      <th className="p-3 text-right">管理員操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200 dark:divide-slate-800/60 font-mono">
                    {adminPlayers.map((p) => {
                      const isCurrent = currentProfile?.id === p.id
                      return (
                        <tr key={p.id} className="hover:bg-slate-100/50 dark:hover:bg-slate-800/40 transition-colors">
                          <td className="p-3 font-sans font-bold text-slate-900 dark:text-slate-100">
                            <div className="flex items-center gap-1.5">
                              {p.name === "Archie" && <Crown className="w-3.5 h-3.5 text-amber-500" />}
                              <span>{p.name}</span>
                              {isCurrent && (
                                <Badge variant="green" className="text-[10px] px-1 py-0">目前視角</Badge>
                              )}
                            </div>
                          </td>
                          <td className="p-3 text-slate-600 dark:text-slate-300">
                            {formatNTD(p.weekly_play_cap)}
                          </td>
                          <td className="p-3 font-bold text-sky-600 dark:text-sky-400">
                            {formatNTD(p.weekly_wallet_balance)}
                          </td>
                          <td className="p-3 font-bold text-emerald-600 dark:text-emerald-400">
                            {formatNTD(p.prize_pool)}
                          </td>
                          <td className={`p-3 font-bold ${p.lifetime_net_profit >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                            {p.lifetime_net_profit >= 0 ? "+" : ""}{formatNTD(p.lifetime_net_profit)}
                          </td>
                          <td className="p-3">
                            <span className={p.is_line_bound ? "text-emerald-500 font-semibold" : "text-slate-400"}>
                              {p.is_line_bound ? "✅ 已綁定" : "未綁定"}
                            </span>
                          </td>
                          <td className="p-3 text-right">
                            {isCurrent ? (
                              <span className="text-slate-400 text-xs">正在檢視中</span>
                            ) : (
                              <button
                                onClick={() => handleAdminDirectSwitch(p)}
                                className="px-2.5 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-600 dark:text-amber-400 text-xs font-bold transition-colors cursor-pointer flex items-center gap-1 ml-auto"
                              >
                                <Eye className="w-3 h-3" />
                                <span>切換此視角</span>
                              </button>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: CREATE NEW PROFILE */}
      {activeTab === "create" && (
        <Card className="border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <CardHeader className="pb-3 border-b border-slate-200 dark:border-slate-800/80">
            <CardTitle className="text-base flex items-center gap-2">
              <UserPlus className="w-4 h-4 text-purple-500" />
              為好友或家庭成員建立新獨立帳號
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <form onSubmit={handleCreateProfile} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">玩家姓名 / 暱稱</label>
                <input
                  type="text"
                  required
                  placeholder="輸入新玩家名稱..."
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-200"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">每週娛樂限額上限 (NT$)</label>
                <input
                  type="number"
                  min={50}
                  step={50}
                  value={newCap}
                  onChange={(e) => setNewCap(Number(e.target.value))}
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-mono text-slate-900 dark:text-slate-200"
                />
                <p className="text-[11px] text-slate-500">預設 NT$ 200，嚴格控管每週最大外部資金風險。</p>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">設定 4 位數 PIN 碼</label>
                <input
                  type="password"
                  maxLength={4}
                  value={createPin}
                  onChange={(e) => setCreatePin(e.target.value.replace(/\D/g, ""))}
                  placeholder="0000"
                  className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-center text-lg font-mono tracking-widest text-slate-900 dark:text-slate-200"
                />
                <p className="text-[11px] text-slate-500">預設為 0000，隨時可於帳號設定變更。</p>
              </div>

              <Button
                type="submit"
                disabled={loading}
                className="w-full font-bold cursor-pointer"
              >
                {loading ? "建立中..." : "確認建立玩家 Profile"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </motion.div>
  )
}
