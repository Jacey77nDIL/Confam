import { create } from "zustand";

type Loc = { latitude: number; longitude: number };

type LocationState = {
  coords: Loc | null;
  status: "unknown" | "pending" | "granted" | "denied" | "unavailable";
  requestLocation: () => void;
};

export const useLocationStore = create<LocationState>((set) => ({
  coords: null,
  status: "unknown",
  requestLocation: () => {
    if (typeof window === "undefined" || !navigator.geolocation) {
      set({ status: "unavailable" });
      return;
    }
    set({ status: "pending" });
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        set({
          coords: {
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
          },
          status: "granted",
        });
      },
      () => set({ status: "denied", coords: null }),
      { enableHighAccuracy: false, maximumAge: 300_000, timeout: 12_000 },
    );
  },
}));
