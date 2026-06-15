import { useState } from 'react'
import { useApp } from '../store'

export function ProfileScreen() {
  const { currentUser, config, authToken, setCurrentUser, goHome, goLogin } = useApp()
  const [name, setName] = useState(currentUser?.name || '')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Password change
  const [showPassword, setShowPassword] = useState(false)
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [logoutConfirm, setLogoutConfirm] = useState(false)

  const studentId = currentUser?.student_id || ''

  const saveName = async () => {
    if (!name.trim()) { setError('姓名不能为空'); return }
    setSaving(true); setError(''); setSuccess('')
    try {
      const r = await fetch(config.apiBase + '/auth/me', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + authToken,
        },
        body: JSON.stringify({ name: name.trim() }),
      })
      if (!r.ok) { const d = await r.json(); setError(d.detail || '保存失败'); return }
      const updated = await r.json()
      setCurrentUser(updated)
      setEditing(false)
      setSuccess('姓名已更新')
      setTimeout(() => setSuccess(''), 2000)
    } catch { setError('网络错误') }
    finally { setSaving(false) }
  }

  const changePassword = async () => {
    if (!newPw || newPw.length < 6) { setError('新密码至少6位'); return }
    setSaving(true); setError(''); setSuccess('')
    try {
      const r = await fetch(config.apiBase + '/auth/me', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + authToken,
        },
        body: JSON.stringify({ password: currentPw, new_password: newPw }),
      })
      if (!r.ok) { const d = await r.json(); setError(d.detail || '修改失败'); return }
      setSuccess('密码已更新')
      setCurrentPw(''); setNewPw(''); setShowPassword(false)
      setTimeout(() => setSuccess(''), 2000)
    } catch { setError('网络错误') }
    finally { setSaving(false) }
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 pt-6 pb-20">
      {/* Header */}
      <div className="text-center mb-8">
        <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-gradient-to-br from-indigo-400 to-purple-400 flex items-center justify-center text-2xl shadow-lg">
          {(name || '?')[0]}
        </div>
        <h2 className="text-lg font-bold text-white">{name || '未命名'}</h2>
        <p className="text-xs text-exam-text-muted mt-1 font-mono">{studentId}</p>
      </div>

      {/* Name */}
      <div className="bg-exam-surface rounded-xl border border-exam-border p-4 mb-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-exam-text-muted font-medium">姓名</span>
          {!editing && (
            <button onClick={() => setEditing(true)} className="text-xs text-exam-accent">编辑</button>
          )}
        </div>
        {editing ? (
          <div className="space-y-3">
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full bg-exam-bg border border-exam-border rounded-lg px-3 py-2.5 text-sm text-exam-text outline-none focus:border-exam-accent"
              placeholder="输入姓名"
            />
            <div className="flex gap-2">
              <button onClick={() => { setEditing(false); setName(currentUser?.name || '') }}
                className="flex-1 py-2 rounded-lg text-sm text-exam-text-muted border border-exam-border">取消</button>
              <button onClick={saveName} disabled={saving}
                className="flex-1 py-2 rounded-lg text-sm text-white bg-exam-accent font-medium disabled:opacity-50">
                {saving ? '保存中…' : '保存'}
              </button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-white">{name || '未设置'}</p>
        )}
      </div>

      {/* Password */}
      <div className="bg-exam-surface rounded-xl border border-exam-border p-4 mb-3">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-exam-text-muted font-medium">密码</span>
          <button onClick={() => setShowPassword(!showPassword)} className="text-xs text-exam-accent">
            {showPassword ? '取消' : (currentPw ? '修改' : '设置')}
          </button>
        </div>
        {showPassword ? (
          <div className="space-y-3">
            <input
              type="password" value={currentPw} onChange={e => setCurrentPw(e.target.value)}
              className="w-full bg-exam-bg border border-exam-border rounded-lg px-3 py-2.5 text-sm text-exam-text outline-none focus:border-exam-accent"
              placeholder="当前密码（未设置过密码则留空）"
            />
            <input
              type="password" value={newPw} onChange={e => setNewPw(e.target.value)}
              className="w-full bg-exam-bg border border-exam-border rounded-lg px-3 py-2.5 text-sm text-exam-text outline-none focus:border-exam-accent"
              placeholder="新密码（至少6位）"
            />
            <button onClick={changePassword} disabled={saving}
              className="w-full py-2.5 rounded-lg text-sm text-white bg-exam-accent font-medium disabled:opacity-50">
              {saving ? '修改中…' : '更新密码'}
            </button>
          </div>
        ) : (
          <p className="text-sm text-exam-text-muted">••••••</p>
        )}
      </div>

      {/* Error / Success */}
      {error && <div className="text-sm text-exam-error text-center mb-3">{error}</div>}
      {success && <div className="text-sm text-exam-success text-center mb-3">{success}</div>}

      {/* Logout */}
      {logoutConfirm ? (
        <div className="bg-exam-surface rounded-xl border border-exam-border p-4 mt-4">
          <p className="text-sm text-exam-text-muted text-center mb-3">退出后需重新登录。确定退出？</p>
          <div className="flex gap-3">
            <button onClick={() => setLogoutConfirm(false)}
              className="flex-1 py-2.5 rounded-lg text-sm text-exam-text-muted border border-exam-border">取消</button>
            <button onClick={goLogin}
              className="flex-1 py-2.5 rounded-lg text-sm text-white bg-exam-error font-medium">确认退出</button>
          </div>
        </div>
      ) : (
        <button onClick={() => setLogoutConfirm(true)}
          className="w-full mt-4 py-3 rounded-xl text-sm text-exam-error border border-exam-error/30 font-medium active:bg-exam-error/5">
          退出登录
        </button>
      )}
    </div>
  )
}
