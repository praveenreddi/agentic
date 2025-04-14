import { bootstrapApplication } from "@angular/platform-browser";
import { AppComponent } from "./app/app.component";
import { appConfig } from "./app/app.config";

// Bootstrap the application with the configuration from app.config.ts
bootstrapApplication(AppComponent, appConfig).catch((err) =>
  console.error("Error bootstrapping app:", err),
);
