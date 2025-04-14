import { Injectable } from "@angular/core";
import { BehaviorSubject } from "rxjs";

export interface Settings {
  fontSize: "small" | "medium" | "large";
  language: string;
  notifications: boolean;
}

const DEFAULT_SETTINGS: Settings = {
  fontSize: "medium",
  language: "en",
  notifications: true,
};

@Injectable({
  providedIn: "root",
})
export class SettingsService {
  private settingsSubject = new BehaviorSubject<Settings>(DEFAULT_SETTINGS);
  settings$ = this.settingsSubject.asObservable();

  constructor() {
    // Load settings from localStorage
    const storedSettings = localStorage.getItem("chatSettings");

    if (storedSettings) {
      try {
        const parsedSettings = JSON.parse(storedSettings);
        this.settingsSubject.next({
          ...DEFAULT_SETTINGS,
          ...parsedSettings,
        });
      } catch (error) {
        console.error("Error parsing stored settings:", error);
        this.settingsSubject.next(DEFAULT_SETTINGS);
      }
    }

    // Apply font size
    this.applyFontSize();
  }

  updateSettings(partialSettings: Partial<Settings>): void {
    const currentSettings = this.settingsSubject.value;
    const newSettings = {
      ...currentSettings,
      ...partialSettings,
    };

    this.settingsSubject.next(newSettings);
    localStorage.setItem("chatSettings", JSON.stringify(newSettings));

    if (partialSettings.fontSize) {
      this.applyFontSize();
    }
  }

  resetSettings(): void {
    this.settingsSubject.next(DEFAULT_SETTINGS);
    localStorage.setItem("chatSettings", JSON.stringify(DEFAULT_SETTINGS));
    this.applyFontSize();
  }

  private applyFontSize(): void {
    const fontSize = this.settingsSubject.value.fontSize;
    const rootElement = document.documentElement;

    rootElement.classList.remove("font-small", "font-medium", "font-large");
    rootElement.classList.add(`font-${fontSize}`);
  }
}
