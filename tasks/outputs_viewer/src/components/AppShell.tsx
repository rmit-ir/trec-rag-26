"use client";
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import AppBar from "@mui/material/AppBar";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Tooltip from "@mui/material/Tooltip";
import Container from "@mui/material/Container";
import DarkModeIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeIcon from "@mui/icons-material/LightModeOutlined";
import PersonIcon from "@mui/icons-material/PersonOutline";
import TravelExploreIcon from "@mui/icons-material/TravelExplore";
import { useColorScheme } from "@mui/material/styles";
import { useIdentity } from "@/lib/client/identity";
import IdentityGate from "./IdentityGate";

const NAV = [
  { href: "/systems", label: "Systems" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/summary", label: "Summary" },
  { href: "/feedback", label: "Feedback" },
];

function ThemeToggle() {
  const { mode, setMode } = useColorScheme();
  const next = mode === "dark" ? "light" : "dark";
  return (
    <Tooltip title={`Switch to ${next} mode`}>
      <IconButton size="small" onClick={() => setMode(next)} color="inherit">
        {mode === "dark" ? <LightModeIcon fontSize="small" /> : <DarkModeIcon fontSize="small" />}
      </IconButton>
    </Tooltip>
  );
}

function UserBadge() {
  const { user, clearUser } = useIdentity();
  const [anchor, setAnchor] = React.useState<null | HTMLElement>(null);
  if (!user) return null;
  return (
    <>
      <Chip
        icon={<PersonIcon />}
        label={user}
        size="small"
        variant="outlined"
        onClick={(e) => setAnchor(e.currentTarget)}
        sx={{ fontWeight: 600 }}
      />
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        <MenuItem
          onClick={() => {
            setAnchor(null);
            clearUser(); // gate re-opens and asks for a new name
          }}
        >
          Switch user
        </MenuItem>
      </Menu>
    </>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <AppBar position="sticky" color="inherit">
        <Toolbar variant="dense" sx={{ gap: 1 }}>
          <TravelExploreIcon color="primary" sx={{ mr: 0.5 }} />
          <Typography
            variant="h6"
            component={Link}
            href="/systems"
            sx={{ color: "inherit", textDecoration: "none", mr: 2, whiteSpace: "nowrap" }}
          >
            RAG Outputs Viewer
          </Typography>
          <Box sx={{ display: "flex", gap: 0.5, flexGrow: 1 }}>
            {NAV.map((item) => {
              const active =
                pathname === item.href ||
                pathname.startsWith(item.href + "/") ||
                (item.href === "/systems" && pathname.startsWith("/session/"));
              return (
                <Button
                  key={item.href}
                  component={Link}
                  href={item.href}
                  size="small"
                  color={active ? "primary" : "inherit"}
                  sx={{
                    fontWeight: active ? 700 : 500,
                    borderBottom: active ? 2 : 2,
                    borderColor: active ? "primary.main" : "transparent",
                    borderRadius: 0,
                  }}
                >
                  {item.label}
                </Button>
              );
            })}
          </Box>
          <UserBadge />
          <ThemeToggle />
        </Toolbar>
      </AppBar>
      <Container maxWidth={false} sx={{ py: 2, flexGrow: 1, px: { xs: 1.5, md: 3 } }}>
        <IdentityGate>{children}</IdentityGate>
      </Container>
    </Box>
  );
}
