import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, Loader2, RefreshCw, ShieldCheck, Trash2, UserPlus } from 'lucide-react'

import {
  createAdminInvite,
  getAdminAccounts,
  getAdminInvites,
  revokeAdminInvite,
  type AdminAccount,
  type AdminInvite,
} from '../../services/api'

const TTL_CHOICES = [1, 6, 24, 72]

const STATUS_STYLE: Record<AdminInvite['status'], { label: string; className: string }> = {
  open: { label: 'Open', className: 'bg-[#e8f5ec] text-[#248a3d]' },
  used: { label: 'Used', className: 'bg-[#f5f5f7] text-[#6e6e73]' },
  expired: { label: 'Expired', className: 'bg-[#fff4e5] text-[#b25e00]' },
}

// Relative wording, because "expires in 4 h" is the question being asked and an
// absolute timestamp makes the reader do the arithmetic.
const untilExpiry = (value: string): string => {
  const moment = new Date(value).getTime()
  if (Number.isNaN(moment)) return ''
  const minutes = Math.round((moment - Date.now()) / 60_000)
  if (minutes <= 0) return 'expired'
  if (minutes < 60) return `${minutes} min left`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h left`
  return `${Math.floor(hours / 24)} d left`
}

// Operator-only view of who has access and which invitations are outstanding.
const AdminPanel = () => {
  const [invites, setInvites] = useState<AdminInvite[]>([])
  const [accounts, setAccounts] = useState<AdminAccount[]>([])
  const [ttlHours, setTtlHours] = useState(24)
  const [minted, setMinted] = useState<{ code: string; expires_at: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    const [nextInvites, nextAccounts] = await Promise.all([
      getAdminInvites(),
      getAdminAccounts(),
    ])
    setInvites(nextInvites)
    setAccounts(nextAccounts)
  }, [])

  useEffect(() => {
    void reload().catch(() => setError('Could not load the operator view.'))
  }, [reload])

  const perform = async (label: string, action: () => Promise<void>) => {
    setBusy(label)
    setError('')
    try {
      await action()
      await reload()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong.')
    } finally {
      setBusy('')
    }
  }

  const mint = () =>
    perform('mint', async () => {
      setMinted(await createAdminInvite(ttlHours))
      setCopied(false)
    })

  const revoke = (invite: AdminInvite) =>
    perform(`revoke-${invite.id}`, () => revokeAdminInvite(invite.id))

  const copyCode = async () => {
    if (!minted) return
    await navigator.clipboard.writeText(minted.code)
    setCopied(true)
  }

  const open = invites.filter(invite => invite.status === 'open')

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
      <div className="mx-auto max-w-4xl">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-[22px] font-semibold tracking-[-0.02em]">
              <ShieldCheck size={20} className="text-[#0071e3]" />
              Operator
            </h2>
            <p className="mt-1 text-sm text-[#6e6e73]">
              Who can reach this machine, and which invitations are still live.
            </p>
          </div>
          <button
            aria-label="Refresh"
            onClick={() => void perform('reload', async () => {})}
            className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-black/[0.08] bg-white hover:bg-[#f5f5f7]"
          >
            <RefreshCw size={16} />
          </button>
        </div>

        {error && (
          <p className="mb-4 rounded-2xl bg-[#fff1f0] px-4 py-3 text-sm text-[#b3261e]">{error}</p>
        )}

        <section className="mb-6 rounded-3xl border border-black/[0.06] bg-white p-5 shadow-sm">
          <h3 className="text-[17px] font-semibold tracking-[-0.01em]">Invite someone</h3>
          <p className="mt-1 text-sm text-[#6e6e73]">
            They choose their own username and password. An invitation is a live path to
            an account on this machine, so give it the shortest life that works.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <select
              value={ttlHours}
              onChange={event => setTtlHours(Number(event.target.value))}
              aria-label="Invitation lifetime"
              className="h-10 rounded-xl border border-black/[0.08] bg-white px-3 text-sm outline-none focus:border-[#0071e3]"
            >
              {TTL_CHOICES.map(hours => (
                <option key={hours} value={hours}>
                  {hours < 24 ? `${hours} hour${hours > 1 ? 's' : ''}` : `${hours / 24} day${hours > 24 ? 's' : ''}`}
                </option>
              ))}
            </select>
            <button
              onClick={() => void mint()}
              disabled={busy !== ''}
              className="flex h-10 items-center gap-2 rounded-xl bg-[#1d1d1f] px-4 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy === 'mint' ? <Loader2 size={15} className="animate-spin" /> : <UserPlus size={15} />}
              Create invitation
            </button>
          </div>

          {minted && (
            <div className="mt-4 rounded-2xl bg-[#f0f7ff] p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[#0055b3]">
                Shown once — only a digest is stored
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <code className="min-w-0 flex-1 break-all rounded-lg bg-white px-3 py-2 font-mono text-sm">
                  {minted.code}
                </code>
                <button
                  onClick={() => void copyCode()}
                  className="flex h-9 items-center gap-1.5 rounded-xl border border-black/[0.08] bg-white px-3 text-sm font-medium"
                >
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <p className="mt-2 text-[11px] leading-4 text-[#6e6e73]">
                Send it however you like. It cannot be shown again — if it reaches the
                wrong person, revoke it below.
              </p>
            </div>
          )}
        </section>

        <section className="mb-6 rounded-3xl border border-black/[0.06] bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-[17px] font-semibold tracking-[-0.01em]">
            Invitations{open.length > 0 && ` — ${open.length} open`}
          </h3>
          {invites.length === 0 ? (
            <p className="text-sm text-[#86868b]">None yet.</p>
          ) : (
            <div className="space-y-2">
              {invites.map(invite => {
                const style = STATUS_STYLE[invite.status] ?? STATUS_STYLE.used
                return (
                  <div
                    key={invite.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-[#f5f5f7] px-3 py-2"
                  >
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${style.className}`}>
                      {style.label}
                    </span>
                    <span className="min-w-0 flex-1 text-sm text-[#1d1d1f]">
                      {invite.consumed_by
                        ? `Used by ${invite.consumed_by}`
                        : untilExpiry(invite.expires_at)}
                    </span>
                    {invite.status === 'open' && (
                      <button
                        onClick={() => void revoke(invite)}
                        disabled={busy !== ''}
                        title="Stop this code from working"
                        className="flex h-8 items-center gap-1.5 rounded-full border border-black/[0.08] bg-white px-3 text-xs font-medium text-[#b3261e] disabled:opacity-40"
                      >
                        {busy === `revoke-${invite.id}` ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          <Trash2 size={12} />
                        )}
                        Revoke
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </section>

        <section className="rounded-3xl border border-black/[0.06] bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-[17px] font-semibold tracking-[-0.01em]">
            Accounts — {accounts.length}
          </h3>
          <div className="space-y-2">
            {accounts.map(account => (
              <div
                key={account.user_id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl bg-[#f5f5f7] px-3 py-2"
              >
                <span className="text-sm font-medium">{account.username}</span>
                {account.is_admin && (
                  <span className="rounded-full bg-[#e8f0fe] px-2 py-0.5 text-[11px] font-medium text-[#0055b3]">
                    Operator
                  </span>
                )}
                {!account.is_active && (
                  <span className="rounded-full bg-[#fff4e5] px-2 py-0.5 text-[11px] font-medium text-[#b25e00]">
                    Disabled
                  </span>
                )}
                <span className="ml-auto text-[11px] text-[#86868b]">
                  {account.created_at ? new Date(account.created_at).toLocaleDateString() : ''}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

export default AdminPanel
