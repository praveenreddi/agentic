import { NgModule } from "@angular/core";
import { BrowserModule } from "@angular/platform-browser";
import { FormsModule } from "@angular/forms";
import { HttpClientModule } from "@angular/common/http";
import { CommonModule } from "@angular/common";
import { AppComponent } from "./app.component";

import { ChatHeaderComponent } from "./components/chat-header/chat-header.component";
import { ChatInputBarComponent } from "./components/chat-input-bar/chat-input-bar.component";
import { ChatMessageComponent } from "./components/chat-message/chat-message.component";
import { ChatHistoryPanelComponent } from "./components/chat-history-panel/chat-history-panel.component";
import { SettingsPanelComponent } from "./components/settings-panel/settings-panel.component";
import { SettingsButtonComponent } from "./components/settings-button/settings-button.component";
import { ThemeToggleComponent } from "./components/theme-toggle/theme-toggle.component";

@NgModule({
  declarations: [
    AppComponent,
    ChatHeaderComponent,
    ChatInputBarComponent,
    ChatMessageComponent,
    ChatHistoryPanelComponent,
    SettingsPanelComponent,
    SettingsButtonComponent,
    ThemeToggleComponent,
  ],
  imports: [BrowserModule, FormsModule, HttpClientModule, CommonModule],
  providers: [],
  bootstrap: [AppComponent],
})
export class AppModule {}
