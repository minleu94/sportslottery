import React, { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { api } from "@/services/api"
import type { Profile } from "@/types"
import { Card, CardContent } from "@/components/ui/Card"
import { Button } from "@/components/ui/Button"
import { Lock, User, KeyRound, UserPlus, ShieldCheck, AlertCircle, Eye, EyeOff } from "lucide-react"

interface LoginGateProps {
  onLoginSuccess: (profile: Profile) => void
}

export const LoginGate: React.FC<LoginGateProps> = ({ onLoginSuccess }) => {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [activeTab, setActiveTab] = useState<"login" | "register" | "pin">("login")
  
  // Login State
  const [selectedIdentifier, setSelectedIdentifier] = useState<string>("")
  const [pinCode, setPinCode] = useState<string>("")
  const [showPin, setShowPin] = useState<boolean>(false)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Register State
  const [regName, setRegName] = useState<string>("")
  const [regCap, setRegCap] = useState<number>(200)
  const [regPin, setRegPin] = useState<string>("0000")
  const [regPinConfirm, setRegPinConfirm] = useState<string>("0000")

  // Change PIN State
  const [changeProfileId, setChangeProfileId] = useState<string>("")
  const [oldPin, setOldPin] = useState<string>("")
  const [newPin, setNewPin] = useState<string>("")
  const [newPinConfirm, setNewPinConfirm] = useState<string>("")

  const selectedProfileObj = profiles.find(
    (p) => p.name.toLowerCase() === selectedIdentifier.trim().toLowerCase() || p.id === selectedIdentifier.trim()
  )
  const isSelectedAdmin = selectedProfileObj
    ? selectedProfileObj.name === "Archie" || selectedProfileObj.id === "default"
    : selectedIdentifier.trim().toLowerCase() === "archie" || selectedIdentifier.trim().toLowerCase() === "default"

  const changeProfileObj = profiles.find((p) => p.id === changeProfileId)
  const isChangeAdmin = changeProfileObj ? (changeProfileObj.name === "Archie" || changeProfileObj.id === "default") : false

  // Admin Reset State (Forgot Password)
  const [isAdminResetMode, setIsAdminResetMode] = useState<boolean>(false)
  const [adminAuthPin, setAdminAuthPin] = useState<string>("")
  const [adminTargetProfileId, setAdminTargetProfileId] = useState<string>("")
  const [adminResetNewPin, setAdminResetNewPin] = useState<string>("0000")

  useEffect(() => {
    loadProfiles()
  }, [])

  async function loadProfiles() {
    try {
      const res = await api.getProfiles()
      const profs = res.profiles || []
      setProfiles(profs)
      if (profs.length > 0) {
        // Check URL query parameters: e.g. ?user=xxx
        const searchParams = new URLSearchParams(window.location.search)
        const userQuery = searchParams.get("user")
        let target = profs[0]
        if (userQuery) {
          const matched = profs.find(
            (p) => p.name.toLowerCase() === userQuery.toLowerCase() || p.id === userQuery
          )
          if (matched) {
            target = matched
          }
        }
        setSelectedIdentifier(target.name)
        setChangeProfileId(target.id)
      }
    } catch (err: any) {
      console.error(err)
    }
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedIdentifier.trim()) {
      setError("請選擇或輸入玩家名稱。")
      return
    }
    if (!pinCode.trim()) {
      setError("請輸入 4 位數 PIN 碼。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await api.loginProfile(selectedIdentifier.trim(), pinCode.trim())
      localStorage.setItem("auth_profile_id", res.profile.id)
      if (res.requires_pin_change) {
        setChangeProfileId(res.profile.id)
        setOldPin(pinCode.trim())
        setActiveTab("pin")
        setError(null)
        setSuccessMsg("👑【管理員首次登入安全設定】目前仍在使用預設密碼 0000，請立即變更為 8 位純數字密碼以解鎖管理功能！")
        return
      }
      onLoginSuccess(res.profile)
    } catch (err: any) {
      setError(err.message || "登入失敗，請確認玩家名稱與 PIN 碼。")
    } finally {
      setLoading(false)
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault()
    if (!regName.trim()) {
      setError("請輸入玩家姓名。")
      return
    }
    if (regPin.length !== 4 || !/^\d{4}$/.test(regPin)) {
      setError("PIN 碼必須為 4 位純數字。")
      return
    }
    if (regPin !== regPinConfirm) {
      setError("兩次輸入的 PIN 碼不一致。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await api.registerProfile(regName.trim(), regCap, regPin)
      localStorage.setItem("auth_profile_id", res.profile.id)
      onLoginSuccess(res.profile)
    } catch (err: any) {
      setError(err.message || "註冊失敗。")
    } finally {
      setLoading(false)
    }
  }

  async function handleAdminResetPinSubmit(e: React.FormEvent) {
    e.preventDefault()
    const targetId = adminTargetProfileId || changeProfileId || (profiles[0]?.id || "default")
    if (!adminAuthPin.trim()) {
      setError("請輸入管理員 Archie 的密碼進行授權。")
      return
    }
    if (adminResetNewPin.length !== 4 || !/^\d{4}$/.test(adminResetNewPin)) {
      setError("新 PIN 碼必須為 4 位純數字。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await api.adminResetPin(targetId, adminResetNewPin, adminAuthPin.trim())
      setSuccessMsg(res.message || "🎉 PIN 碼已由管理員成功重設！現在請以此新密碼登入。")
      setAdminAuthPin("")
      setIsAdminResetMode(false)
      setActiveTab("login")
    } catch (err: any) {
      setError(err.message || "管理員授權失敗，無法重設密碼。")
    } finally {
      setLoading(false)
    }
  }

  async function handleChangePin(e: React.FormEvent) {
    e.preventDefault()
    if (!oldPin) {
      setError("請輸入目前 PIN 碼。")
      return
    }
    if (isChangeAdmin) {
      if (newPin.length !== 8 || !/^\d{8}$/.test(newPin)) {
        setError("管理員密碼必須剛好為 8 位純數字（例如：12345678）。")
        return
      }
    } else {
      if (newPin.length !== 4 || !/^\d{4}$/.test(newPin)) {
        setError("新 PIN 碼必須為 4 位純數字。")
        return
      }
    }
    if (newPin !== newPinConfirm) {
      setError("兩次輸入的新密碼不一致。")
      return
    }

    setLoading(true)
    setError(null)
    setSuccessMsg(null)
    try {
      const res = await api.updateProfile({
        profile_id: changeProfileId,
        current_pin: oldPin,
        new_pin: newPin,
      })
      if (res.token) {
        api.setAuthToken(res.token)
      }
      setSuccessMsg(isChangeAdmin ? "🎉 管理員 8 位密碼變更成功！請以此新密碼登入。" : "PIN 碼變更成功！請以此新 PIN 碼登入。")
      setOldPin("")
      setNewPin("")
      setNewPinConfirm("")
      setActiveTab("login")
    } catch (err: any) {
      setError(err.message || "變更密碼失敗。")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-100/70 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        className="w-full max-w-md"
      >
        {/* Brand Header */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-emerald-500/10 dark:bg-emerald-500/15 border border-emerald-500/20 text-4xl mb-3 select-none">
            🐕
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white flex items-center justify-center gap-2">
            台灣運彩 <span className="text-emerald-600 dark:text-emerald-400 font-bold">瘋狗流</span> 決策系統
          </h1>
          <div className="flex items-center justify-center gap-2 mt-1.5">
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-200/70 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-300/60 dark:border-slate-700/60">
              v2.3.0
            </span>
            <span className="text-xs text-slate-500 dark:text-slate-400">成員專用登入 · 多玩家獨立娛樂資金池</span>
          </div>
        </div>

        {/* Auth Box */}
        <Card className="border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs overflow-hidden">
          {/* Tabs */}
          <div className="grid grid-cols-3 border-b border-slate-200 dark:border-slate-800 text-center text-xs font-medium">
            <button
              onClick={() => { setActiveTab("login"); setError(null); setSuccessMsg(null) }}
              className={`py-3 transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                activeTab === "login"
                  ? "border-b-2 border-emerald-600 text-emerald-600 dark:text-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/20"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <KeyRound className="w-3.5 h-3.5" />
              登入
            </button>
            <button
              onClick={() => { setActiveTab("register"); setError(null); setSuccessMsg(null) }}
              className={`py-3 transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                activeTab === "register"
                  ? "border-b-2 border-emerald-600 text-emerald-600 dark:text-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/20"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <UserPlus className="w-3.5 h-3.5" />
              註冊
            </button>
            <button
              onClick={() => { setActiveTab("pin"); setError(null); setSuccessMsg(null) }}
              className={`py-3 transition-colors cursor-pointer flex items-center justify-center gap-1.5 ${
                activeTab === "pin"
                  ? "border-b-2 border-emerald-600 text-emerald-600 dark:text-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/20"
                  : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              變更 PIN
            </button>
          </div>

          <CardContent className="p-5 sm:p-6">
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2"
              >
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </motion.div>
            )}

            {successMsg && (
              <motion.div
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2"
              >
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>{successMsg}</span>
              </motion.div>
            )}

            {/* TAB 1: LOGIN */}
            {activeTab === "login" && (
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5 flex items-center gap-1">
                    <User className="w-3.5 h-3.5 text-slate-400" />
                    選擇或輸入玩家名稱
                  </label>
                  {profiles.length > 0 ? (
                    <div className="space-y-2">
                      <select
                        value={selectedIdentifier}
                        onChange={(e) => setSelectedIdentifier(e.target.value)}
                        className="w-full px-3 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                      >
                        {profiles.map((p) => (
                          <option key={p.id} value={p.name}>
                            👤 {p.name} (每週上限 NT$ {p.weekly_play_cap})
                          </option>
                        ))}
                      </select>
                      <input
                        type="text"
                        placeholder="或輸入其他玩家名稱..."
                        value={selectedIdentifier}
                        onChange={(e) => setSelectedIdentifier(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-slate-950/60 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                  ) : (
                    <input
                      type="text"
                      placeholder="輸入玩家名稱 (如：Archie)..."
                      value={selectedIdentifier}
                      onChange={(e) => setSelectedIdentifier(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                    />
                  )}
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-semibold text-slate-300 flex items-center gap-1">
                      <Lock className="w-3.5 h-3.5 text-slate-400" />
                      {isSelectedAdmin ? "8 位純數字密碼" : "4 位數 PIN 碼"}
                    </label>
                    <span className="text-[11px] text-slate-400">
                      {isSelectedAdmin ? "首次預設 0000" : "預設為 0000"}
                    </span>
                  </div>
                  <div className="relative">
                    <input
                      type={showPin ? "text" : "password"}
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={isSelectedAdmin ? 8 : 4}
                      value={pinCode}
                      onChange={(e) => setPinCode(e.target.value.replace(/\D/g, ""))}
                      placeholder={isSelectedAdmin ? "••••••••" : "••••"}
                      className="w-full px-3 py-2.5 rounded-lg bg-slate-950 border border-slate-800 text-white text-center text-lg tracking-widest font-mono focus:outline-none focus:border-emerald-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPin(!showPin)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                    >
                      {showPin ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold cursor-pointer"
                >
                  {loading ? "登入中..." : "🔑 登入決策台"}
                </Button>
              </form>
            )}

            {/* TAB 2: REGISTER */}
            {activeTab === "register" && (
              <form onSubmit={handleRegister} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">玩家姓名 / 代號</label>
                  <input
                    type="text"
                    required
                    placeholder="輸入新玩家姓名..."
                    value={regName}
                    onChange={(e) => setRegName(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">每週娛樂額度上限 (NT$)</label>
                  <input
                    type="number"
                    min={50}
                    step={50}
                    value={regCap}
                    onChange={(e) => setRegCap(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">健康風控預算，預設每週 NT$ 200</p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">設定 4 位 PIN</label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={regPin}
                      onChange={(e) => setRegPin(e.target.value.replace(/\D/g, ""))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">確認 PIN</label>
                    <input
                      type="password"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={4}
                      value={regPinConfirm}
                      onChange={(e) => setRegPinConfirm(e.target.value.replace(/\D/g, ""))}
                      className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                </div>

                <Button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold cursor-pointer"
                >
                  {loading ? "建立中..." : "✨ 建立玩家帳號並進入"}
                </Button>
              </form>
            )}

            {/* TAB 3: CHANGE PIN / ADMIN RESET */}
            {activeTab === "pin" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800 text-xs">
                  <span className="text-slate-400 font-medium">
                    {isAdminResetMode ? "👑 管理員協助重設 (免舊密碼)" : "🔒 一般會員修改密碼 (需舊密碼)"}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setIsAdminResetMode(!isAdminResetMode)
                      setError(null)
                      setSuccessMsg(null)
                    }}
                    className="text-amber-400 hover:text-amber-300 font-bold underline cursor-pointer"
                  >
                    {isAdminResetMode ? "切換回一般修改" : "❓ 忘記密碼？管理員協助重設"}
                  </button>
                </div>

                {isAdminResetMode ? (
                  <form onSubmit={handleAdminResetPinSubmit} className="space-y-4">
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">
                        選擇要重設密碼的成員
                      </label>
                      <select
                        value={adminTargetProfileId || changeProfileId}
                        onChange={(e) => {
                          setAdminTargetProfileId(e.target.value)
                          setChangeProfileId(e.target.value)
                        }}
                        className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-amber-500"
                      >
                        {profiles.map((p) => (
                          <option key={p.id} value={p.id}>
                            👤 {p.name} {p.name === "Archie" ? "(管理員)" : ""}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-xs font-semibold text-amber-400 flex items-center gap-1">
                          👑 輸入管理員 Archie 的密碼授權
                        </label>
                      </div>
                      <input
                        type="password"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        maxLength={8}
                        required
                        value={adminAuthPin}
                        onChange={(e) => setAdminAuthPin(e.target.value.replace(/\D/g, ""))}
                        placeholder="請輸入 Archie 的密碼 (預設 0000 或 8 位數字)"
                        className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-amber-500/50 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-amber-400"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">
                        設定該成員之新 PIN 碼 (預設 0000)
                      </label>
                      <input
                        type="password"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        maxLength={4}
                        required
                        value={adminResetNewPin}
                        onChange={(e) => setAdminResetNewPin(e.target.value.replace(/\D/g, ""))}
                        placeholder="0000"
                        className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-amber-500"
                      />
                      <p className="text-[11px] text-slate-500 mt-1">重設後成員即可立即以新 PIN 碼登入。</p>
                    </div>

                    <Button
                      type="submit"
                      disabled={loading}
                      variant="amber"
                      className="w-full py-2.5 font-bold cursor-pointer"
                    >
                      {loading ? "授權重設中..." : "🔄 執行管理員授權重設"}
                    </Button>
                  </form>
                ) : (
                  <form onSubmit={handleChangePin} className="space-y-4">
                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">選擇玩家</label>
                      <select
                        value={changeProfileId}
                        onChange={(e) => setChangeProfileId(e.target.value)}
                        className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-sm focus:outline-none focus:border-emerald-500"
                      >
                        {profiles.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-slate-300 mb-1">
                        目前舊密碼 / PIN 碼
                      </label>
                      <input
                        type="password"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        maxLength={isChangeAdmin ? 8 : 4}
                        value={oldPin}
                        onChange={(e) => setOldPin(e.target.value.replace(/\D/g, ""))}
                        placeholder={isChangeAdmin ? "預設 0000 或 8 位數字" : "預設 0000"}
                        className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-semibold text-slate-300 mb-1">
                          {isChangeAdmin ? "新 8 位純數字密碼" : "新 4 位 PIN"}
                        </label>
                        <input
                          type="password"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          maxLength={isChangeAdmin ? 8 : 4}
                          value={newPin}
                          onChange={(e) => setNewPin(e.target.value.replace(/\D/g, ""))}
                          placeholder={isChangeAdmin ? "8 位純數字" : "4 位純數字"}
                          className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-300 mb-1">
                          確認新密碼
                        </label>
                        <input
                          type="password"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          maxLength={isChangeAdmin ? 8 : 4}
                          value={newPinConfirm}
                          onChange={(e) => setNewPinConfirm(e.target.value.replace(/\D/g, ""))}
                          placeholder={isChangeAdmin ? "再次輸入 8 位數" : "再次輸入 4 位數"}
                          className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white text-center font-mono tracking-widest text-sm focus:outline-none focus:border-emerald-500"
                        />
                      </div>
                    </div>

                    <Button
                      type="submit"
                      disabled={loading}
                      className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold cursor-pointer"
                    >
                      {loading ? "更新中..." : "🔒 確認變更 PIN 碼"}
                    </Button>
                  </form>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>
    </div>
  )
}
