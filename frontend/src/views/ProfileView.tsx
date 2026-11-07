import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { Profile } from "@/types"
import { formatNTD } from "@/lib/utils"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { User, KeyRound, Shield, CheckCircle2, AlertCircle, Crown, Eye, UserPlus, RefreshCw, Trash2, Settings2, Bell, Link2, Unlink } from "lucide-react"
import { Dialog } from "@/components/ui/Dialog"

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

type LinePreferences = Record<"steam_drop" | "ticket_settlement" | "hedging_alert" | "morning_radar", boolean>
type LineBindingRequest = { request_id: string; display_name: string; confirmation_code: string; created_at: string; expires_at: string }

export const ProfileView: React.FC<ProfileViewProps> = ({ currentProfile, onProfileChange }) => {
  const isAdmin = currentProfile?.id === "default"
  const [activeTab, setActiveTab] = useState<"edit" | "admin_overview" | "create">("edit")

  const [profiles, setProfiles] = useState<Profile[]>([])
  const [selectedProfileId, setSelectedProfileId] = useState<string>(currentProfile?.id || "default")
  const [pinCode, setPinCode] = useState<string>("")
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null)
  const [lineBound, setLineBound] = useState(false)
  const [linePreferences, setLinePreferences] = useState<LinePreferences>({ steam_drop: true, ticket_settlement: true, hedging_alert: true, morning_radar: true })
  const [lineRequests, setLineRequests] = useState<LineBindingRequest[]>([])
  const [lineLoading, setLineLoading] = useState(false)

  // Edit settings
  const [editName, setEditName] = useState<string>(currentProfile?.name || "")
  const [editCap, setEditCap] = useState<number>(currentProfile?.weekly_play_cap || 200)
  const [currentPinForEdit, setCurrentPinForEdit] = useState<string>("")
  const [newPin, setNewPin] = useState<string>("")

  // Admin Overview & Player Governance
  const [adminPlayers, setAdminPlayers] = useState<PlayerOverviewItem[]>([])
  const [loadingAdmin, setLoadingAdmin] = useState(false)
  const [adminActionLoading, setAdminActionLoading] = useState(false)

  // Admin Action Dialogs
  const [deletePlayerTarget, setDeletePlayerTarget] = useState<PlayerOverviewItem | null>(null)
  const [deletePlayerHistory, setDeletePlayerHistory] = useState(true)
  const [resetPinPlayerTarget, setResetPinPlayerTarget] = useState<PlayerOverviewItem | null>(null)
  const [editPlayerTarget, setEditPlayerTarget] = useState<PlayerOverviewItem | null>(null)
  const [editPlayerName, setEditPlayerName] = useState("")
  const [editPlayerCap, setEditPlayerCap] = useState(200)

  // Create Profile Form
  const [newName, setNewName] = useState("")
  const [newCap, setNewCap] = useState(200)
  const [createPin, setCreatePin] = useState("0000")

  useEffect(() => {
    loadProfiles()
    void loadLineSettings()
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

  async function loadLineSettings() {
    setLineLoading(true)
    try {
      const [settings, pending] = await Promise.all([api.getLineSettings(), api.getLineBindingRequests()])
      setLineBound(settings.bound)
      setLinePreferences(settings.preferences)
      setLineRequests(pending.requests || [])
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "載入 LINE 綁定與通知設定失敗" })
    } finally {
      setLineLoading(false)
    }
  }

  async function handleSaveLinePreferences() {
    setLineLoading(true)
    try {
      const result = await api.saveLineSettings(linePreferences)
      setLinePreferences(result.preferences)
      setMessage({ type: "success", text: "LINE 通知偏好已更新。" })
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "儲存 LINE 通知偏好失敗" })
    } finally {
      setLineLoading(false)
    }
  }

  async function handleLineBinding(requestId: string, approve: boolean) {
    setLineLoading(true)
    try {
      if (approve) await api.approveLineBindingRequest(requestId)
      else await api.rejectLineBindingRequest(requestId)
      await loadLineSettings()
      setMessage({ type: "success", text: approve ? "LINE 帳號已綁定至目前 Profile。" : "已拒絕 LINE 綁定申請。" })
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "處理 LINE 綁定申請失敗" })
    } finally {
      setLineLoading(false)
    }
  }

  async function handleUnbindLine() {
    if (!window.confirm("解除此 Profile 的 LINE 綁定？之後需重新提出並核准綁定申請。")) return
    setLineLoading(true)
    try {
      await api.unbindLineProfile()
      await loadLineSettings()
      setMessage({ type: "success", text: "已解除目前 Profile 的 LINE 綁定。" })
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "解除 LINE 綁定失敗" })
    } finally {
      setLineLoading(false)
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
    const isTargetAdmin = selectedProfileId === "default"
    if (!pinCode.trim()) {
      setMessage({ type: "error", text: isTargetAdmin ? "請輸入 8 位管理員密碼（首次預設 0000）" : "請輸入 4 位數 PIN 碼（預設 0000）" })
      return
    }
    setLoading(true)
    setMessage(null)

    try {
      const res = await api.verifyPin(selectedProfileId, pinCode.trim())
      onProfileChange(res.profile)
      setMessage({ type: "success", text: `已成功切換為【${res.profile.name}】身分！` })
      setPinCode("")
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || (isTargetAdmin ? "管理員密碼錯誤" : "PIN 碼錯誤") })
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
    if (newPin) {
      if (isAdmin) {
        if (newPin.length !== 8 || !/^\d{8}$/.test(newPin)) {
          setMessage({ type: "error", text: "管理員密碼必須剛好為 8 位純數字（例如：12345678）。" })
          return
        }
      } else {
        if (newPin.length !== 4 || !/^\d{4}$/.test(newPin)) {
          setMessage({ type: "error", text: "PIN 碼必須為 4 位純數字。" })
          return
        }
      }
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
      if (res.token) {
        api.setAuthToken(res.token)
      }
      onProfileChange(res.profile)
      setMessage({ type: "success", text: res.message || "個人設定已成功更新！" })
      setCurrentPinForEdit("")
      setNewPin("")
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "更新失敗" })
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirmDelete() {
    if (!deletePlayerTarget) return
    setAdminActionLoading(true)
    try {
      const res = await api.adminDeletePlayer(deletePlayerTarget.id, deletePlayerHistory)
      setMessage({ type: "success", text: res.message || `已成功刪除玩家【${deletePlayerTarget.name}】！` })
      setDeletePlayerTarget(null)
      await loadProfiles()
      if (isAdmin) await loadAdminPlayers()
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "刪除玩家失敗" })
    } finally {
      setAdminActionLoading(false)
    }
  }

  async function handleConfirmResetPin() {
    if (!resetPinPlayerTarget) return
    setAdminActionLoading(true)
    try {
      const res = await api.adminResetPin(resetPinPlayerTarget.id, "0000")
      setMessage({ type: "success", text: res.message || `已成功將【${resetPinPlayerTarget.name}】的 PIN 碼重設為 0000！` })
      setResetPinPlayerTarget(null)
      await loadProfiles()
      if (isAdmin) await loadAdminPlayers()
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "重設 PIN 碼失敗" })
    } finally {
      setAdminActionLoading(false)
    }
  }

  async function handleConfirmEditPlayer(e: React.FormEvent) {
    e.preventDefault()
    if (!editPlayerTarget) return
    setAdminActionLoading(true)
    try {
      const res = await api.adminUpdatePlayer({
        profile_id: editPlayerTarget.id,
        name: editPlayerName.trim() || undefined,
        weekly_play_cap: editPlayerCap,
      })
      setMessage({ type: "success", text: res.message || `已成功更新玩家【${editPlayerName}】的管理設定！` })
      setEditPlayerTarget(null)
      await loadProfiles()
      if (isAdmin) await loadAdminPlayers()
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "更新玩家設定失敗" })
    } finally {
      setAdminActionLoading(false)
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
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="max-w-4xl mx-auto space-y-5"
    >
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2 tracking-tight">
          <User className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
          個人設定與風控管理
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          獨立資金帳本、PIN 碼隱私防護與多玩家娛樂額度設定
        </p>
      </div>

      {isAdmin && (
        <div className="p-3.5 rounded-xl bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-500 shrink-0">
              <Crown className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-bold text-amber-800 dark:text-amber-300 flex items-center gap-1.5">
                👑 系統最高管理員 (Archie) · 特權已啟用
              </div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400">
                您享有管理員完整權限：全體玩家資金監察、預算限額調整、一鍵切換視角與特權重設密碼。
              </div>
            </div>
          </div>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-300 border border-amber-500/40 shrink-0 self-start sm:self-auto">
            👑 ADMIN ACTIVE
          </span>
        </div>
      )}

      {message && (
        <div
          className={`p-3.5 rounded-xl text-xs flex items-center gap-2 ${
            message.type === "success"
              ? "bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-500/20 text-emerald-700 dark:text-emerald-300"
              : "bg-rose-50 dark:bg-rose-950/30 border border-rose-500/20 text-rose-700 dark:text-rose-300"
          }`}
        >
          {message.type === "success" ? <CheckCircle2 className="w-4 h-4 text-emerald-600" /> : <AlertCircle className="w-4 h-4 text-rose-600" />}
          <span>{message.text}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-800 gap-1.5 pb-2 overflow-x-auto scrollbar-none">
        <button
          onClick={() => setActiveTab("edit")}
          className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 whitespace-nowrap ${
            activeTab === "edit"
              ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
              : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          }`}
        >
          <User className="w-3.5 h-3.5 text-slate-400" />
          <span>編輯個人設定</span>
        </button>

        {isAdmin && (
          <button
            onClick={() => {
              setActiveTab("admin_overview")
              loadAdminPlayers()
            }}
            className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 whitespace-nowrap ${
              activeTab === "admin_overview"
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/40 shadow-xs"
                : "text-amber-600/80 dark:text-amber-400/80 hover:text-amber-700 dark:hover:text-amber-300"
            }`}
          >
            <Crown className="w-3.5 h-3.5 text-amber-500" />
            <span>全體玩家總覽 (管理員特權)</span>
          </button>
        )}

        <button
          onClick={() => setActiveTab("create")}
          className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 whitespace-nowrap ${
            activeTab === "create"
              ? "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 border border-slate-200 dark:border-slate-700 shadow-xs"
              : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
          }`}
        >
          <UserPlus className="w-3.5 h-3.5 text-slate-400" />
          <span>新增玩家 Profile</span>
        </button>
      </div>

      {/* TAB 1: EDIT SETTINGS */}
      {activeTab === "edit" && (
        <div className="space-y-5">
          {/* Switch Profile Card */}
          <Card className="border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
            <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Shield className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                切換帳號身分
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-700 dark:text-slate-300">選擇帳號</label>
                <select
                  value={selectedProfileId}
                  onChange={(e) => setSelectedProfileId(e.target.value)}
                  className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-800 dark:text-slate-200 cursor-pointer"
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.id === "default" ? `👑 ${p.name} (管理員)` : p.name} (每週上限: {formatNTD(p.weekly_play_cap)})
                    </option>
                  ))}
                </select>
              </div>

              {(() => {
                const isSelectedSwitchAdmin = selectedProfileId === "default"
                return (
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                      <KeyRound className="w-3.5 h-3.5 text-slate-400" />
                      {isSelectedSwitchAdmin ? "輸入 8 位管理員密碼 (首次預設 0000)" : "輸入 4 位數 PIN 碼 (預設: 0000)"}
                    </label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={isSelectedSwitchAdmin ? 8 : 4}
                      value={pinCode}
                      onChange={(e) => setPinCode(e.target.value.replace(/\D/g, ""))}
                      placeholder={isSelectedSwitchAdmin ? "••••••••" : "••••"}
                      className="w-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-center text-lg font-mono tracking-widest text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                  </div>
                )
              })()}

              <Button
                variant="default"
                onClick={handleSwitchProfile}
                disabled={loading}
                className="w-full font-medium cursor-pointer"
              >
                確認切換身分
              </Button>
            </CardContent>
          </Card>

          {/* Edit Profile Settings Card */}
          <Card className="border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
            <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <User className="w-4 h-4 text-slate-400" />
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
                  <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                    {isAdmin ? "變更新密碼 (管理員必須剛好為 8 位純數字，留空則不變)" : "變更新 PIN 碼 (留空則不變)"}
                  </label>
                  <input
                    type="password"
                    maxLength={isAdmin ? 8 : 4}
                    value={newPin}
                    onChange={(e) => setNewPin(e.target.value.replace(/\D/g, ""))}
                    placeholder={isAdmin ? "8 位純數字新密碼" : "4 位數新 PIN"}
                    className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm font-mono text-slate-900 dark:text-slate-200"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-amber-600 dark:text-amber-400">
                    {isAdmin ? "輸入目前密碼驗證授權 (首次預設 0000)" : "輸入目前 PIN 碼驗證授權"}
                  </label>
                  <input
                    type="password"
                    maxLength={isAdmin ? 8 : 4}
                    value={currentPinForEdit}
                    onChange={(e) => setCurrentPinForEdit(e.target.value.replace(/\D/g, ""))}
                    placeholder={isAdmin ? "目前 8 位密碼或 0000" : "目前 4 位 PIN"}
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

          <Card className="border-slate-200/80 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs">
            <CardHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Link2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                LINE 綁定與通知
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 pt-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-800 dark:text-slate-200">LINE 狀態：{lineBound ? "已綁定目前 Profile" : "尚未綁定"}</div>
                  <p className="text-xs text-slate-500 mt-1">
                    {lineBound
                      ? "私人 Wallet 與本站注單只會依此 Profile 顯示。解綁或重新綁定需在主系統操作。"
                      : `在 LINE 私人對話傳送「綁定請求 ${currentProfile?.name || "玩家名稱"}」，再核對 LINE 回覆與下方相同的確認碼。只核准你剛才親自發起的申請，不確定時請拒絕。`}
                  </p>
                </div>
                <button onClick={() => void loadLineSettings()} disabled={lineLoading} aria-label="重新整理 LINE 設定" className="p-2 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-emerald-600 disabled:opacity-50">
                  <RefreshCw className={`w-4 h-4 ${lineLoading ? "animate-spin" : ""}`} />
                </button>
              </div>

              {lineBound && (
                <Button variant="ghost" onClick={handleUnbindLine} disabled={lineLoading} className="text-rose-600 border border-rose-200 dark:border-rose-900/60">
                  <Unlink className="w-4 h-4 mr-2" />解除 LINE 綁定
                </Button>
              )}

              {lineRequests.length > 0 && (
                <div className="space-y-2 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50/70 dark:bg-amber-950/20 p-3">
                  <div className="text-xs font-semibold text-amber-800 dark:text-amber-300">待確認申請（10 分鐘內有效）</div>
                  {lineRequests.map((request) => (
                    <div key={request.request_id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-md bg-white dark:bg-slate-900 p-2.5">
                      <div className="text-xs text-slate-700 dark:text-slate-300">
                        確認碼：<b className="font-mono tracking-wider">{request.confirmation_code}</b>
                        <div className="text-[11px] text-slate-500">申請：{new Date(request.created_at).toLocaleString()}</div>
                        <div className="text-[11px] text-slate-500">到期：{new Date(request.expires_at).toLocaleString()}</div>
                      </div>
                      <div className="flex gap-2 shrink-0">
                        <Button onClick={() => void handleLineBinding(request.request_id, true)} disabled={lineLoading} className="h-8 px-3 text-xs">核准綁定</Button>
                        <Button variant="ghost" onClick={() => void handleLineBinding(request.request_id, false)} disabled={lineLoading} className="h-8 px-3 text-xs">拒絕</Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="border-t border-slate-100 dark:border-slate-800 pt-3 space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-300"><Bell className="w-3.5 h-3.5" />此 Profile 的 LINE 通知</div>
                {([
                  ["steam_drop", "重要賠率變動"],
                  ["ticket_settlement", "本站注單結算"],
                  ["hedging_alert", "聽牌／對沖提醒"],
                  ["morning_radar", "每日 Radar 摘要"],
                ] as const).map(([key, label]) => (
                  <label key={key} className="flex items-center justify-between gap-3 py-1 text-xs text-slate-600 dark:text-slate-300">
                    <span>{label}</span>
                    <input
                      type="checkbox"
                      checked={linePreferences[key]}
                      disabled={!lineBound || lineLoading}
                      onChange={(event) => setLinePreferences((previous) => ({ ...previous, [key]: event.target.checked }))}
                      className="h-4 w-4 accent-emerald-600"
                    />
                  </label>
                ))}
                <Button onClick={handleSaveLinePreferences} disabled={!lineBound || lineLoading} className="w-full text-xs">
                  儲存 LINE 通知偏好
                </Button>
                {!lineBound && <p className="text-[11px] text-slate-500">完成 LINE 綁定後可設定通知。LINE 使用者身分與偏好只套用於目前 Profile。</p>}
              </div>
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
              <div className="overflow-x-auto scrollbar-none">
                <table className="w-full text-left text-xs min-w-[720px]">
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
                              {p.id === "default" && <Crown className="w-3.5 h-3.5 text-amber-500" />}
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
                            {p.id === "default" ? (
                              <div className="flex items-center justify-end gap-1.5">
                                <Badge variant="amber" className="text-[10px]">👑 系統管理者</Badge>
                                {!isCurrent && (
                                  <button
                                    onClick={() => handleAdminDirectSwitch(p)}
                                    className="px-2 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-600 dark:text-amber-400 text-xs font-bold transition-colors cursor-pointer flex items-center gap-1"
                                  >
                                    <Eye className="w-3 h-3" />
                                    <span>切回 Archie</span>
                                  </button>
                                )}
                              </div>
                            ) : (
                              <div className="flex items-center justify-end gap-1.5 flex-wrap">
                                {isCurrent ? (
                                  <Badge variant="green" className="text-[10px]">目前視角</Badge>
                                ) : (
                                  <button
                                    onClick={() => handleAdminDirectSwitch(p)}
                                    title="切換至該玩家視角"
                                    className="px-2 py-1 rounded bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-sky-600 dark:text-sky-400 text-xs font-bold transition-colors cursor-pointer flex items-center gap-1"
                                  >
                                    <Eye className="w-3 h-3" />
                                    <span>切換</span>
                                  </button>
                                )}
                                <button
                                  onClick={() => {
                                    setEditPlayerTarget(p)
                                    setEditPlayerName(p.name)
                                    setEditPlayerCap(p.weekly_play_cap)
                                  }}
                                  title="管理玩家每週限額與暱稱"
                                  className="px-2 py-1 rounded bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 text-indigo-600 dark:text-indigo-400 text-xs font-bold transition-colors cursor-pointer flex items-center gap-1"
                                >
                                  <Settings2 className="w-3 h-3" />
                                  <span>設定</span>
                                </button>
                                <button
                                  onClick={() => setResetPinPlayerTarget(p)}
                                  title="重設 PIN 碼為 0000"
                                  className="px-2 py-1 rounded bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-600 dark:text-amber-400 text-xs font-bold transition-colors cursor-pointer flex items-center gap-1"
                                >
                                  <KeyRound className="w-3 h-3" />
                                  <span>重設PIN</span>
                                </button>
                                <button
                                  onClick={() => { setDeletePlayerHistory(true); setDeletePlayerTarget(p) }}
                                  title="永久刪除此玩家"
                                  className="px-2 py-1 rounded bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-rose-600 dark:text-rose-400 text-xs font-bold transition-colors cursor-pointer flex items-center gap-1"
                                >
                                  <Trash2 className="w-3 h-3" />
                                  <span>刪除</span>
                                </button>
                              </div>
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
      {/* Admin Action: Delete Player Dialog */}
      <Dialog
        open={!!deletePlayerTarget}
        onClose={() => setDeletePlayerTarget(null)}
        title={
          <div className="flex items-center gap-2 text-rose-500 font-bold">
            <Trash2 className="w-5 h-5" />
            <span>永久刪除玩家帳號確認</span>
          </div>
        }
        description="此為不可復原之高風險動作，請管理員 Archie 謹慎確認。"
      >
        {deletePlayerTarget && (
          <div className="space-y-4 pt-2">
            <div className="p-3.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs space-y-1.5">
              <p className="font-bold text-sm text-rose-400">
                ⚠️ 即將永久刪除玩家【{deletePlayerTarget.name}】（ID: {deletePlayerTarget.id}）
              </p>
              <p>玩家帳號與錢包會刪除。請選擇是否同時刪除投注與帳本歷史：</p>
              <ul className="list-disc list-inside space-y-0.5 text-slate-300 pl-1">
                <li>本週錢包可玩餘額：<b className="text-white">{formatNTD(deletePlayerTarget.weekly_wallet_balance)}</b></li>
                <li>保留儲備池：<b className="text-white">{formatNTD(deletePlayerTarget.prize_pool)}</b></li>
                <li>歷史投注注單紀錄與所有帳本明細（可選擇保留）</li>
              </ul>
            </div>

            <fieldset className="space-y-2 text-sm text-slate-200">
              <legend className="font-semibold">歷史資料處理</legend>
              <label className="flex items-start gap-2 rounded-lg border border-slate-700 p-3 cursor-pointer">
                <input type="radio" name="delete-player-history" checked={deletePlayerHistory} onChange={() => setDeletePlayerHistory(true)} className="mt-0.5 accent-rose-500" />
                <span>一併刪除所有投注與帳本紀錄</span>
              </label>
              <label className="flex items-start gap-2 rounded-lg border border-slate-700 p-3 cursor-pointer">
                <input type="radio" name="delete-player-history" checked={!deletePlayerHistory} onChange={() => setDeletePlayerHistory(false)} className="mt-0.5 accent-emerald-500" />
                <span>保留投注與帳本紀錄</span>
              </label>
            </fieldset>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                variant="ghost"
                onClick={() => setDeletePlayerTarget(null)}
                disabled={adminActionLoading}
              >
                取消
              </Button>
              <Button
                variant="destructive"
                onClick={handleConfirmDelete}
                disabled={adminActionLoading}
                className="font-bold flex items-center gap-1.5"
              >
                <Trash2 className="w-4 h-4" />
                <span>{adminActionLoading ? "刪除處理中..." : "確認永久刪除"}</span>
              </Button>
            </div>
          </div>
        )}
      </Dialog>

      {/* Admin Action: Reset PIN Dialog */}
      <Dialog
        open={!!resetPinPlayerTarget}
        onClose={() => setResetPinPlayerTarget(null)}
        title={
          <div className="flex items-center gap-2 text-amber-400 font-bold">
            <KeyRound className="w-5 h-5" />
            <span>管理員重設玩家 PIN 碼</span>
          </div>
        }
        description="管理員 Archie 特權：免舊密碼直接將成員 PIN 碼重設為預設值。"
      >
        {resetPinPlayerTarget && (
          <div className="space-y-4 pt-2">
            <p className="text-sm text-slate-300">
              您確定要將玩家【<b className="text-white">{resetPinPlayerTarget.name}</b>】的 4 位數 PIN 碼重設為預設值 <code className="bg-slate-800 px-1.5 py-0.5 rounded text-amber-300 font-mono font-bold">0000</code> 嗎？
            </p>
            <p className="text-xs text-slate-400">重設後成員可立即使用 0000 登入並自行變更密碼。</p>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                variant="ghost"
                onClick={() => setResetPinPlayerTarget(null)}
                disabled={adminActionLoading}
              >
                取消
              </Button>
              <Button
                variant="amber"
                onClick={handleConfirmResetPin}
                disabled={adminActionLoading}
                className="font-bold flex items-center gap-1.5"
              >
                <KeyRound className="w-4 h-4" />
                <span>{adminActionLoading ? "重設中..." : "確認重設為 0000"}</span>
              </Button>
            </div>
          </div>
        )}
      </Dialog>

      {/* Admin Action: Edit Player Settings Dialog */}
      <Dialog
        open={!!editPlayerTarget}
        onClose={() => setEditPlayerTarget(null)}
        title={
          <div className="flex items-center gap-2 text-indigo-400 font-bold">
            <Settings2 className="w-5 h-5" />
            <span>管理員編輯玩家設定</span>
          </div>
        }
        description="直接調整玩家暱稱或每週娛樂預算限額。"
      >
        {editPlayerTarget && (
          <form onSubmit={handleConfirmEditPlayer} className="space-y-4 pt-2">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">玩家姓名 / 暱稱</label>
              <input
                type="text"
                required
                value={editPlayerName}
                onChange={(e) => setEditPlayerName(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">每週娛樂限額上限 (NT$)</label>
              <input
                type="number"
                min={10}
                max={100000}
                step={50}
                required
                value={editPlayerCap}
                onChange={(e) => setEditPlayerCap(Number(e.target.value))}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm font-mono text-slate-100"
              />
              <p className="text-[11px] text-slate-500">每週重置時允許自動注入錢包的額度上限。</p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setEditPlayerTarget(null)}
                disabled={adminActionLoading}
              >
                取消
              </Button>
              <Button
                type="submit"
                variant="default"
                disabled={adminActionLoading}
                className="font-bold flex items-center gap-1.5"
              >
                <span>{adminActionLoading ? "儲存中..." : "儲存設定變更"}</span>
              </Button>
            </div>
          </form>
        )}
      </Dialog>
    </motion.div>
  )
}
