import {
  Component,
  ElementRef,
  OnInit,
  ViewChild,
  AfterViewChecked,
} from "@angular/core";
import { CommonModule } from "@angular/common";
import { HttpClientModule } from "@angular/common/http";
import { ChatService, ChatSession, Message } from "../services/chat.service";
import { ThemeService } from "../services/theme.service";
import { SettingsService } from "../services/settings.service";
import { ChatHistoryPanelComponent } from "../components/chat-history-panel/chat-history-panel.component";
import { ChatInputBarComponent } from "../components/chat-input-bar/chat-input-bar.component";
import { ChatMessageComponent } from "../components/chat-message/chat-message.component";
import { ChatHeaderComponent } from "../components/chat-header/chat-header.component";
import { SettingsPanelComponent } from "../components/settings-panel/settings-panel.component";
import { SettingsButtonComponent } from "../components/settings-button/settings-button.component";
import { firstValueFrom } from "rxjs";
import { FormsModule } from "@angular/forms";
import { MsalService } from "@azure/msal-angular";
import { environment } from "../../environments/environment";

@Component({
  selector: "app-chat-page",
  templateUrl: "./chat-page.component.html",
  styleUrls: ["./chat-page.component.scss"],
  standalone: true,
  imports: [
    CommonModule,
    HttpClientModule,
    ChatHistoryPanelComponent,
    ChatInputBarComponent,
    ChatMessageComponent,
    ChatHeaderComponent,
    SettingsPanelComponent,
    SettingsButtonComponent,
    FormsModule,
  ],
})
export class ChatPageComponent implements OnInit, AfterViewChecked {
  @ViewChild("messagesEnd") messagesEnd!: ElementRef;

  // User ID
  userId = "";
  userName = "";
  ssoEnabled = environment.enableSSO;

  // Chat state
  messages: Message[] = [];
  sessions: ChatSession[] = [];
  activeSessionId: string | null = null;
  isLoading = false;

  // Panel state
  isHistoryOpen = true;
  isHistoryCollapsed = true;
  isSettingsOpen = false;

  // Theme state
  isDarkMode = false;

  newMessage = "";
  isTyping = false;

  constructor(
    private chatService: ChatService,
    private themeService: ThemeService,
    private settingsService: SettingsService,
    private authService: MsalService,
  ) {}

  ngOnInit() {
    // Get user information from MSAL if SSO is enabled
    if (this.ssoEnabled) {
      try {
        const account =
          this.authService.instance.getActiveAccount() ||
          this.authService.instance.getAllAccounts()[0];
        if (account) {
          this.userId = account.localAccountId || "";
          this.userName = account.name || "User";
          console.log("User authenticated:", {
            id: this.userId,
            name: this.userName,
          });
        }
      } catch (error) {
        console.error("Error getting user account:", error);
      }
    }

    this.initializeChat();

    this.themeService.isDarkMode$.subscribe((isDark) => {
      this.isDarkMode = isDark;
    });
  }

  ngAfterViewChecked() {
    this.scrollToBottom();
  }

  scrollToBottom(): void {
    if (this.messagesEnd) {
      try {
        this.messagesEnd.nativeElement.scrollIntoView({ behavior: "smooth" });
      } catch (err) {
        console.error("Error scrolling to bottom:", err);
      }
    }
  }

  // Copy all the methods from AppComponent related to chat functionality
  async initializeChat() {
    this.isLoading = true;
    try {
      // Load existing sessions
      const fetchedSessions = await firstValueFrom(
        this.chatService.fetchSessions(this.userId),
      );
      this.sessions = fetchedSessions;

      // Create a new chat session
      const newSession = await firstValueFrom(
        this.chatService.createSession(this.userId),
      );

      // Set as active session
      this.activeSessionId = newSession.id;

      // Add welcome message
      const welcomeMessage: Message = {
        id: crypto.randomUUID(),
        content: this.chatService.getWelcomeMessage(),
        role: "bot",
        timestamp: Date.now(),
      };
      this.messages = [welcomeMessage];
    } catch (error) {
      console.error("Error during initialization:", error);
      // Create a fallback session if everything fails
      const fallbackSession = {
        id: crypto.randomUUID(),
        title: "New Chat",
        timestamp: Date.now(),
        previewMessage: "Start a new conversation",
      };
      this.sessions = [fallbackSession];
      this.activeSessionId = fallbackSession.id;
    } finally {
      this.isLoading = false;
    }
  }

  async createNewChat() {
    try {
      const newSession = await firstValueFrom(
        this.chatService.createSession(this.userId),
      );
      this.sessions = [newSession, ...this.sessions];
      return newSession;
    } catch (error) {
      console.error("Error creating new chat:", error);
      const fallbackSession = {
        id: crypto.randomUUID(),
        title: "New Chat",
        timestamp: Date.now(),
        previewMessage: "Start a new conversation",
      };
      return fallbackSession;
    }
  }

  handleSelectSession(sessionId: string): void {
    this.activeSessionId = sessionId;
    // Load messages for the selected session
    this.loadMessagesForSession(sessionId);
  }

  async loadMessagesForSession(sessionId: string): Promise<void> {
    if (!sessionId) return;

    try {
      const messages = await firstValueFrom(
        this.chatService.fetchMessages(this.userId, sessionId),
      );
      this.messages = messages;
    } catch (error) {
      console.error("Error loading messages:", error);
      this.messages = [
        {
          id: crypto.randomUUID(),
          content: "Failed to load messages. Please try again.",
          role: "bot",
          timestamp: Date.now(),
        },
      ];
    }
  }

  async handleSendMessage(content: string) {
    if (!this.activeSessionId) return;

    // Add user message to UI immediately
    const userMessage: Message = {
      id: crypto.randomUUID(),
      content,
      role: "user",
      timestamp: Date.now(),
    };

    // Add bot message placeholder
    const botMessageId = crypto.randomUUID();
    const botMessage: Message = {
      id: botMessageId,
      content: "",
      role: "bot",
      timestamp: Date.now(),
      isStreaming: true,
    };

    this.messages = [...this.messages, userMessage, botMessage];

    try {
      const botResponse = await firstValueFrom(
        this.chatService.createMessage(
          this.userId,
          this.activeSessionId,
          content,
        ),
      );

      // Update the UI with the bot response
      this.messages = this.messages.map((m) =>
        m.id === botMessageId
          ? { ...m, content: botResponse.content, isStreaming: false }
          : m,
      );

      // Refresh sessions to update previews
      this.loadSessions();
    } catch (error) {
      console.error("Error getting response:", error);

      this.messages = this.messages.map((m) =>
        m.id === botMessageId
          ? {
              ...m,
              content: "Sorry, there was an error processing your request.",
              isStreaming: false,
            }
          : m,
      );
    }
  }

  async handleRegenerate() {
    if (!this.activeSessionId || this.messages.length < 2) return;

    // Get the last user message
    const lastUserMessageIndex = this.messages
      .map((m) => m.role)
      .lastIndexOf("user");

    if (lastUserMessageIndex === -1) return;

    const lastUserMessage = this.messages[lastUserMessageIndex];

    // Remove the last bot message
    this.messages = this.messages.slice(0, -1);

    // Call handleSendMessage with the last user message content
    await this.handleSendMessage(lastUserMessage.content);
  }

  async handleDeleteMessage(messageId: string) {
    this.messages = this.messages.filter((m) => m.id !== messageId);
  }

  async handleDeleteSession(sessionId: string): Promise<void> {
    try {
      const success = await firstValueFrom(
        this.chatService.deleteSession(this.userId, sessionId),
      );
      if (success) {
        this.sessions = this.sessions.filter((s) => s.id !== sessionId);

        // If the deleted session was active, select another one
        if (this.activeSessionId === sessionId) {
          if (this.sessions.length > 0) {
            this.activeSessionId = this.sessions[0].id;
            await this.loadMessagesForSession(this.sessions[0].id);
          } else {
            // Create a new session if there are none left
            const newSession = await this.createNewChat();
            this.activeSessionId = newSession.id;
          }
        }
      }
    } catch (error) {
      console.error("Error deleting session:", error);
    }
  }

  async loadSessions(): Promise<void> {
    try {
      const fetchedSessions = await firstValueFrom(
        this.chatService.fetchSessions(this.userId),
      );
      this.sessions = fetchedSessions;
    } catch (error) {
      console.error("Error loading sessions:", error);
    }
  }

  toggleHistory(): void {
    this.isHistoryOpen = !this.isHistoryOpen;
  }

  togglePanelCollapse(): void {
    this.isHistoryCollapsed = !this.isHistoryCollapsed;
  }

  toggleSettings(): void {
    this.isSettingsOpen = !this.isSettingsOpen;
  }

  getContentPaddingClass(): string {
    if (this.isHistoryOpen) {
      return this.isHistoryCollapsed ? "pl-60" : "pl-280";
    }
    return "";
  }
}
