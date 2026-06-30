import { create } from 'zustand';

export const useFeedbackStore = create((set) => ({
    hasSubmitted: false,
    isOpen: false,
    currentRating: 0,
    setHasSubmitted: (val) => set({ hasSubmitted: Boolean(val) }),
    setIsOpen: (val) => set({ isOpen: Boolean(val) }),
    setCurrentRating: (val) => set({ currentRating: Number(val) || 0 }),
}));