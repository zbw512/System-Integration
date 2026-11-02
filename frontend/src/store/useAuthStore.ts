import { create } from "zustand";
import {
  getCurrentAccount,
  loginAccount,
  logoutAccount,
  registerAccount,
} from "../api/auth";
import type { AuthUser } from "../types";

interface AuthStore {
  user: AuthUser | null;
  initialized: boolean;
  busy: boolean;
  error: string | null;
  lastClaimedGuestJobs: number;
  initialize: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    password: string,
    displayName?: string
  ) => Promise<void>;
  logout: () => Promise<void>;
  markSignedOut: () => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthStore>((set, get) => ({
  user: null,
  initialized: false,
  busy: false,
  error: null,
  lastClaimedGuestJobs: 0,

  initialize: async () => {
    if (get().initialized || get().busy) {
      return;
    }
    set({ busy: true });
    try {
      const response = await getCurrentAccount();
      set({
        user: response.authenticated ? response.user : null,
        initialized: true,
        busy: false,
        error: null,
        lastClaimedGuestJobs: 0,
      });
    } catch {
      // An unavailable account service must not block anonymous VLM use.
      set({
        user: null,
        initialized: true,
        busy: false,
        lastClaimedGuestJobs: 0,
      });
    }
  },

  login: async (username, password) => {
    set({ busy: true, error: null });
    try {
      const response = await loginAccount(username, password);
      set({
        user: response.user,
        busy: false,
        initialized: true,
        lastClaimedGuestJobs: response.guest_claim?.jobs ?? 0,
      });
    } catch (error) {
      set({ busy: false });
      throw error;
    }
  },

  register: async (username, password, displayName) => {
    set({ busy: true, error: null });
    try {
      const response = await registerAccount({
        username,
        password,
        display_name: displayName?.trim() || undefined,
      });
      set({
        user: response.user,
        busy: false,
        initialized: true,
        lastClaimedGuestJobs: response.guest_claim?.jobs ?? 0,
      });
    } catch (error) {
      set({ busy: false });
      throw error;
    }
  },

  logout: async () => {
    set({ busy: true, error: null });
    try {
      await logoutAccount();
      set({ user: null, busy: false, lastClaimedGuestJobs: 0 });
    } catch (error) {
      set({ busy: false });
      throw error;
    }
  },

  markSignedOut: () =>
    set({
      user: null,
      initialized: true,
      busy: false,
      lastClaimedGuestJobs: 0,
    }),

  clearError: () => set({ error: null }),
}));
