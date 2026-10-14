// API response types.

export type FileKind = 'video' | 'audio' | 'image' | 'other'
export type FileStatus = 'uploading' | 'ready'
export type MediaStatus = 'none' | 'pending' | 'done' | 'failed'
export type Playable = 'yes' | 'maybe' | 'no'
export type PlayMode = 'none' | 'original' | 'remux'
export type EventKind = 'view' | 'download' | 'zip' | 'play'

export interface PublicFile {
  id: string
  name: string
  size: number
  mime: string
  kind: FileKind
  status: FileStatus
  media_status: MediaStatus
  playable: Playable
  duration: number | null
  width: number | null
  height: number | null
  url: string | null
  download_url: string | null
  play_url: string | null
  poster_url: string | null
}

export interface PublicShare {
  slug: string
  title: string | null
  created_at: number
  expires_at: number | null
  protected: boolean
  unlocked: boolean
  total_size: number | null
  file_count: number | null
  files: PublicFile[]
}

/** Server disk space. */
export interface Disk {
  used: number
  total: number
  free: number
}

export type Role = 'user' | 'admin'

/** Who is signed in. */
export interface User {
  login: string
  /** Used to sign in. */
  email: string | null
  role: Role
  /** Limit in bytes; null — unlimited. */
  quota: number | null
  used: number
  /** Admin role on the internal network: user management is available. */
  admin_panel: boolean
}

export type SessionInfo = { authenticated: false } | { authenticated: true; user: User }

export interface Usage {
  quota: number | null
  used: number
  free: number | null
  /** Administrator only. */
  disk: Disk | null
}

export interface TokenInfo {
  kind: 'invite' | 'reset'
  /** Invitation — to this address; reset — the password of the account with this address. */
  email: string | null
  login: string | null
}

export interface AdminUser {
  id: number
  login: string
  email: string | null
  role: Role
  quota: number | null
  used: number
  share_count: number
  created_at: number
  last_login_at: number | null
  blocked: boolean
}

export interface UsersResponse {
  users: AdminUser[]
  disk: Disk
  /** Sum of limits of users who have one. */
  allocated: number
  /** Default limit for a new user; null — unlimited. */
  default_quota: number | null
}

export interface Invite {
  id: number
  email: string
  quota: number | null
  created_at: number
  expires_at: number
}

/** A new invitation or a new link to an existing one — the previous link stops working. */
export interface CreatedInvite extends Invite {
  url: string
}

export interface UserUpdate {
  quota?: number | null
  blocked?: boolean
}

export interface AdminShareSummary {
  slug: string
  url: string
  title: string | null
  display_title: string
  created_at: number
  expires_at: number | null
  expired: boolean
  protected: boolean
  file_count: number
  total_size: number
  uploading_count: number
  views: number
  downloads: number
  plays: number
  last_access_at: number | null
}

export interface AdminFile extends PublicFile {
  uploaded: number | null
  play: PlayMode
  video_codec: string | null
  audio_codec: string | null
  created_at: number
  completed_at: number | null
}

export interface ShareEvent {
  ts: number
  kind: EventKind
  file_id: string | null
  file_name: string | null
  ip: string | null
  user_agent: string | null
}

export interface AdminShareDetail extends AdminShareSummary {
  files: AdminFile[]
  events: ShareEvent[]
}

export interface ShareSettingsInput {
  title?: string | null
  expires_at?: number | null
  password?: string | null
}
