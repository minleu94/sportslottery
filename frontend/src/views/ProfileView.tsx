import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { Profile } from "@/types"
import { formatNTD } from "@/lib/utils"
import { Button } from "@/components/ui/Button"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card"
import { User, KeyRound, Shield, CheckCircle2, AlertCircle } from "lucide-react"

interface ProfileViewProps {
  currentProfile: Profile | null
  onProfileChange: (profile: Profile) => void
}

export const ProfileView: React.FC<ProfileViewProps> = ({ currentProfile, onProfileChange }) => {
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

  useEffect(() => {
    loadProfiles()
  }, [])

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

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="max-w-2xl mx-auto space-y-6"
    >
      <div>
        <h2 className="text-xl font-black text-slate-900 dark:text-slate-100 flex items-center gap-2">
          <User className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
          個人設定與風控上限 (Player Profile & Safety)
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          獨立錢包帳本、PIN 碼隱私防護與每週理性投注額度管理
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
            className="w-full font-bold"
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
            className="w-full font-bold"
          >
            儲存風控設定
          </Button>
        </CardContent>
      </Card>
    </motion.div>
  )
}
