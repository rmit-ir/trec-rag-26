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
import SettingsBrightnessIcon from "@mui/icons-material/SettingsBrightnessOutlined";
import PersonIcon from "@mui/icons-material/PersonOutline";
import TravelExploreIcon from "@mui/icons-material/TravelExplore";
import MenuIcon from "@mui/icons-material/Menu";
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
  const { mode, systemMode, setMode } = useColorScheme();
  const [anchor, setAnchor] = React.useState<null | HTMLElement>(null);
  const resolved = mode === "system" ? systemMode : mode;
  const icon =
    mode === "system"
      ? <SettingsBrightnessIcon fontSize="small" />
      : resolved === "dark"
        ? <DarkModeIcon fontSize="small" />
        : <LightModeIcon fontSize="small" />;
  return (
    <>
      <Tooltip title={`Theme: ${mode ?? "system"}${mode === "system" && resolved ? ` (${resolved})` : ""}`}>
        <IconButton
          size="small"
          onClick={(event) => setAnchor(event.currentTarget)}
          color="inherit"
        >
          {icon}
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {(["system", "light", "dark"] as const).map((value) => (
          <MenuItem
            key={value}
            selected={mode === value}
            onClick={() => {
              setMode(value);
              setAnchor(null);
            }}
          >
            {value === "system" ? "System" : value === "light" ? "Light" : "Dark"}
          </MenuItem>
        ))}
      </Menu>
    </>
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

function isNavActive(pathname: string, href: string): boolean {
  return (
    pathname === href ||
    pathname.startsWith(href + "/") ||
    (href === "/systems" && pathname.startsWith("/session/"))
  );
}

/** Hamburger nav for narrow screens (hidden on md+). */
function MobileNav({ pathname }: { pathname: string }) {
  const [anchor, setAnchor] = React.useState<null | HTMLElement>(null);
  return (
    <Box sx={{ display: { xs: "flex", md: "none" }, alignItems: "center" }}>
      <IconButton
        size="small"
        color="inherit"
        aria-label="Open navigation menu"
        onClick={(e) => setAnchor(e.currentTarget)}
      >
        <MenuIcon fontSize="small" />
      </IconButton>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {NAV.map((item) => (
          <MenuItem
            key={item.href}
            component={Link}
            href={item.href}
            selected={isNavActive(pathname, item.href)}
            onClick={() => setAnchor(null)}
          >
            {item.label}
          </MenuItem>
        ))}
      </Menu>
    </Box>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <AppBar position="sticky" color="inherit">
        <Toolbar variant="dense" sx={{ gap: { xs: 0.5, md: 1 }, minWidth: 0 }}>
          <MobileNav pathname={pathname} />
          <TravelExploreIcon color="primary" sx={{ mr: 0.5, display: { xs: "none", sm: "block" } }} />
          <Typography
            component={Link}
            href="/systems"
            sx={{
              color: "inherit",
              textDecoration: "none",
              mr: { xs: 1, md: 2 },
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              fontSize: { xs: "1rem", md: "1.25rem" },
              fontWeight: 500,
              minWidth: 0,
            }}
          >
            RAG Outputs Viewer
          </Typography>
          <Box sx={{ display: { xs: "none", md: "flex" }, gap: 0.5, flexGrow: 1 }}>
            {NAV.map((item) => {
              const active = isNavActive(pathname, item.href);
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
          <Box sx={{ flexGrow: 1, display: { xs: "block", md: "none" } }} />
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
