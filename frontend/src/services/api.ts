import { sportsApi } from "./api/sports"
import { walletApi } from "./api/wallet"
import { profilesApi } from "./api/profiles"
import { researchApi } from "./api/research"
import { getAuthToken, setAuthToken } from "./api/shared"

export { ApiRequestError, getAuthToken, setAuthToken } from "./api/shared"
export type { SearchParlaysParams } from "./api/sports"

// Preserve the existing api.* call surface while keeping request domains together.
export const api = {
  getAuthToken,
  setAuthToken,
  ...sportsApi,
  ...walletApi,
  ...profilesApi,
  ...researchApi,
}
