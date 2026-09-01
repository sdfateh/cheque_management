import { Banknote, LayoutDashboard, ListChecks } from "lucide-react";
import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";

import App from "./App";
import { __ } from "./lib/i18n";
import { initTheme } from "./lib/theme";
import ChequeDashboard from "./routes/ChequeDashboard";
import Cheques from "./routes/Cheques";
import "./index.css";

// The /cheques entry point. Cheque management is its own product with its own
// audience and its own permissions; it consumes the shared Sanawbar component
// package and has an independent build. There is deliberately no link to the manufacturing
// side - someone who works in both opens whichever one they mean.
//
// Two screens, because they answer different questions: the dashboard is "what
// needs me today", the list is "find me this cheque". Filters live in the list's
// URL, so every tile and shortcut on the dashboard is just a link into it.

initTheme();

const router = createBrowserRouter(
	[
		{
			path: "/",
			element: (
				<App
					brand={{ label: "Cheques", icon: Banknote }}
					deskHref="/app/mfg-cheque"
					links={[
						{ to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
						{ to: "/list", label: "All Cheques", icon: ListChecks },
					]}
				/>
			),
			children: [
				{ index: true, element: <ChequeDashboard /> },
				{ path: "list", element: <Cheques /> },
				{ path: "*", element: <Navigate to="/" replace /> },
			],
		},
	],
	{ basename: "/cheques" }
);

ReactDOM.createRoot(document.getElementById("root")).render(
	<React.StrictMode>
		<RouterProvider router={router} />
	</React.StrictMode>
);
