import { Injectable } from "@angular/core";
import { BehaviorSubject } from "rxjs";

@Injectable({
  providedIn: "root",
})
export class ThemeService {
  private darkModeSubject = new BehaviorSubject<boolean>(false);
  isDarkMode$ = this.darkModeSubject.asObservable();

  constructor() {
    // Check if user has a preference stored
    const storedPreference = localStorage.getItem("darkMode");

    if (storedPreference) {
      this.darkModeSubject.next(storedPreference === "true");
    } else {
      // Check if user prefers dark mode at the OS level
      const prefersDark = window.matchMedia(
        "(prefers-color-scheme: dark)",
      ).matches;
      this.darkModeSubject.next(prefersDark);
    }

    // Apply the theme
    this.applyTheme();
  }

  toggleDarkMode(): void {
    const newValue = !this.darkModeSubject.value;
    this.darkModeSubject.next(newValue);
    localStorage.setItem("darkMode", String(newValue));
    this.applyTheme();
  }

  private applyTheme(): void {
    if (this.darkModeSubject.value) {
      document.body.classList.add("dark-mode");
    } else {
      document.body.classList.remove("dark-mode");
    }
  }
}
