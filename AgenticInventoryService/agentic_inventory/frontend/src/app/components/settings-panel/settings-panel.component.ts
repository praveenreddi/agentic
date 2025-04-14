import { Component, EventEmitter, OnInit, Output } from "@angular/core";
import { Settings, SettingsService } from "../../services/settings.service";
import { ThemeService } from "../../services/theme.service";
import { CommonModule } from "@angular/common";

@Component({
  selector: "app-settings-panel",
  templateUrl: "./settings-panel.component.html",
  styleUrls: ["./settings-panel.component.scss"],
  standalone: true,
  imports: [CommonModule],
})
export class SettingsPanelComponent implements OnInit {
  @Output() close = new EventEmitter<void>();

  settings: Settings = {
    fontSize: "medium",
    language: "en",
    notifications: true,
  };

  isDarkMode = false;

  languages = [
    { code: "en", name: "English" },
    { code: "es", name: "Spanish" },
    { code: "fr", name: "French" },
    { code: "de", name: "German" },
    { code: "zh", name: "Chinese" },
    { code: "ja", name: "Japanese" },
  ];

  constructor(
    private settingsService: SettingsService,
    private themeService: ThemeService,
  ) {}

  ngOnInit(): void {
    this.settingsService.settings$.subscribe((settings) => {
      this.settings = settings;
    });

    this.themeService.isDarkMode$.subscribe((isDark) => {
      this.isDarkMode = isDark;
    });
  }

  onClose(): void {
    this.close.emit();
  }

  updateFontSize(size: "small" | "medium" | "large"): void {
    this.settingsService.updateSettings({ fontSize: size });
  }

  updateLanguage(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.settingsService.updateSettings({ language: select.value });
  }

  toggleNotifications(): void {
    this.settingsService.updateSettings({
      notifications: !this.settings.notifications,
    });
  }

  toggleDarkMode(): void {
    this.themeService.toggleDarkMode();
  }

  resetSettings(): void {
    this.settingsService.resetSettings();
  }
}
