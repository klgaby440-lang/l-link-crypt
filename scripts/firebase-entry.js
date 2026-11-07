import {
  initializeApp, getApps, getApp
} from "firebase/app";
import {
  getAuth, signInWithPopup, signInWithCustomToken, GoogleAuthProvider, onAuthStateChanged, signOut
} from "firebase/auth";

globalThis.LlinkFirebaseSDK = {
  initializeApp, getApps, getApp,
  getAuth, signInWithPopup, signInWithCustomToken, GoogleAuthProvider, onAuthStateChanged, signOut
};
