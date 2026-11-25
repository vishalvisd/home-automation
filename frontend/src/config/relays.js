import {
  Camera,
  Droplets,
  Gauge,
  Leaf,
  Router,
  Waves,
  Zap,
} from "lucide-react";

export const RELAYS = [
  {
    key: "ro_power",
    name: "RO Purifier",
    channel: "IN1",
    gpio: 2,
    icon: Droplets,
    description: "Reverse osmosis water purifier power.",
    wiringNote: "Relay OFF supplies power through the normally closed contact.",
  },
  {
    key: "router_power",
    name: "Main Router",
    channel: "IN2",
    gpio: 3,
    icon: Router,
    description: "Terrace optical network unit and main router power.",
    wiringNote:
      "Relay OFF supplies power through the normally closed contact. Relay ON cuts the router's power.",
    // The safe way to switch the router off: the Pi brings the power
    // back by itself, because this page cannot ask for it once the
    // router is off.
    restart: {
      label: "Restart router",
      note: "Cuts the router's power and brings it back by itself, after the time set for the nightly restart (30 seconds unless changed). The internet and every camera are away for about two minutes.",
      confirm:
        "Restart the router now?\n\nThe internet and every camera are away for about two minutes. The power comes back by itself.",
      done: (seconds) =>
        `The router's power goes off in a moment for ${seconds} seconds and comes back by itself. This page cannot reach the Pi for about two minutes.`,
    },
    // The plain relay buttons stay, inside a red box, and Relay ON asks
    // first.
    danger: {
      note: "Kill switch. Relay ON cuts the router's power and it stays off. With the router off nothing on the home network can reach the Pi, this page included, so Relay OFF cannot be pressed afterwards. Someone has to go to the Pi. Use Restart router instead.",
      confirm:
        "Really cut the router's power and leave it off?\n\nThis page will not be able to switch it back on. Someone has to go to the Pi.",
    },
  },
  {
    key: "camera_power",
    name: "Camera Power Line",
    channel: "IN3",
    gpio: 12,
    icon: Camera,
    description: "Shared power line for the ESP32 cameras.",
    wiringNote: "Relay ON supplies power through the normally open contact.",
  },
  {
    key: "plant_valve",
    name: "Plant Solenoid Valve",
    channel: "IN4",
    gpio: 13,
    icon: Leaf,
    description: "Controls water flow to the plant-watering pipeline.",
    wiringNote: "Relay ON opens the normally closed solenoid valve.",
  },
  {
    key: "main_valve",
    name: "Main Motorised Valve",
    channel: "IN5",
    gpio: 26,
    icon: Waves,
    description: "Controls the main water path for sprinklers and plants.",
    wiringNote: "Relay ON selects opening; relay OFF selects closing.",
  },
  {
    key: "pump",
    name: "Water Pump",
    channel: "IN6",
    gpio: 21,
    icon: Gauge,
    description: "Controls the overhead-tank pump circuit.",
    wiringNote: "Relay ON activates the pump control circuit.",
  },
  {
    key: "valve_power",
    name: "Valve System Power",
    channel: "IN8",
    gpio: 16,
    icon: Zap,
    description: "Supplies power to the main valve and plant valve circuits.",
    wiringNote: "Relay ON supplies power through the normally open contact.",
  },
];