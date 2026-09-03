import AsyncStorage from '@react-native-async-storage/async-storage';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import React, { useState } from 'react';
import {
  Alert,
  Linking,
  PermissionsAndroid,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { RifoOverlay } from '../overlay';
import type { RootStackParamList } from '../navigation';

type Props = NativeStackScreenProps<RootStackParamList, 'Onboarding'>;

const ONBOARDED_KEY = 'rifo.onboarded';

type StepId = 'notifications' | 'overlay' | 'screenCapture';
interface Step {
  id: StepId;
  title: string;
  body: string;
  done: boolean;
  required: boolean;
}

const BASE_STEPS: Step[] = [
  {
    id: 'notifications',
    title: 'Notifications',
    body: 'Lets Rifo show a result alert when a check finishes in the background.',
    done: false,
    required: true,
  },
  {
    id: 'overlay',
    title: 'Display over other apps',
    body: 'Required for the floating bubble that sits above every app.',
    done: false,
    required: true,
  },
  {
    id: 'screenCapture',
    title: 'Screen capture',
    body: 'One-time consent lets the bubble capture whatever is on screen when you long-press it.',
    done: false,
    required: true,
  },
];

/** POST_NOTIFICATIONS only exists on API 33+ (FR-9, constraint #22). */
async function requestNotifications(): Promise<boolean> {
  if (Platform.Version < 33) {
    return true; // permission does not exist below Android 13 — do not request
  }
  try {
    const granted = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
    );
    return granted === PermissionsAndroid.RESULTS.GRANTED;
  } catch {
    return false;
  }
}

export default function OnboardingScreen({ navigation }: Props): React.JSX.Element {
  const [steps, setSteps] = useState<Step[]>(BASE_STEPS);
  const [busy, setBusy] = useState<StepId | null>(null);

  const stepById = (id: StepId): Step => steps.find((s) => s.id === id)!;
  const mark = (id: StepId, done: boolean): void =>
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, done } : s)));

  async function runStep(step: Step): Promise<void> {
    setBusy(step.id);
    try {
      let ok = false;
      if (step.id === 'notifications') {
        ok = await requestNotifications();
        if (!ok) {
          Alert.alert('Notifications off', 'You can enable them later in Settings. Rifo still works.');
        }
        mark('notifications', true); // non-blocking by design
      } else if (step.id === 'overlay') {
        ok = await RifoOverlay.requestOverlayPermission();
        if (!ok && RifoOverlay.available) {
          Alert.alert(
            'Overlay permission needed',
            'Rifo needs "Display over other apps" for the bubble. Open Settings to enable it.',
            [{ text: 'Open settings', onPress: () => Linking.openSettings() }, { text: 'Later' }],
          );
          return; // keep step pending so the user can retry
        }
        mark('overlay', RifoOverlay.available ? ok : true);
      } else {
        // screenCapture — MediaProjection consent. On grant the native side
        // starts the foreground service + bubble automatically.
        ok = await RifoOverlay.requestScreenCapture();
        if (!ok && RifoOverlay.available) {
          Alert.alert('Capture not granted', 'Screen capture is required to verify content. Tap to retry.');
          return; // keep pending
        }
        mark('screenCapture', true);
      }
    } finally {
      setBusy(null);
    }
  }

  async function advance(): Promise<void> {
    const next = steps.find((s) => !s.done);
    if (!next) {
      await finish();
      return;
    }
    await runStep(next);
  }

  async function finish(): Promise<void> {
    await AsyncStorage.setItem(ONBOARDED_KEY, '1');
    // Root navigator swaps to the History stack on next render; reset clears backstack.
    navigation.reset({ index: 0, routes: [{ name: 'History' }] });
  }

  /** Allows the RN shell to be exercised before the Kotlin overlay exists. */
  async function devSkip(): Promise<void> {
    await finish();
  }

  const allDone = steps.every((s) => s.done);
  const nextPending = steps.find((s) => !s.done);

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.logo}>Rifo</Text>
      <Text style={styles.tagline}>Check what is really on your screen.</Text>
      <Text style={styles.intro}>
        Long-press the floating bubble to verify any claim in the app you are using. We need three
        permissions:
      </Text>

      <View style={styles.steps}>
        {steps.map((s) => (
          <View key={s.id} style={[styles.step, s.done && styles.stepDone]}>
            <View style={[styles.dot, s.done && styles.dotDone]}>
              {s.done ? <Text style={styles.dotCheck}>✓</Text> : null}
            </View>
            <View style={styles.stepText}>
              <Text style={styles.stepTitle}>{s.title}</Text>
              <Text style={styles.stepBody}>{s.body}</Text>
            </View>
          </View>
        ))}
      </View>

      <Pressable
        onPress={advance}
        disabled={busy != null}
        style={[styles.primary, (busy != null || allDone) && styles.primaryDim]}>
        <Text style={styles.primaryText}>
          {busy != null
            ? 'Waiting…'
            : allDone
            ? 'Start verifying'
            : nextPending?.id === 'screenCapture'
            ? 'Allow screen capture'
            : 'Continue'}
        </Text>
      </Pressable>

      {!RifoOverlay.available ? (
        <Pressable onPress={devSkip} style={styles.devSkip}>
          <Text style={styles.devSkipText}>
            Native overlay not present (dev shell) — continue without permissions
          </Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flexGrow: 1, padding: 24, backgroundColor: '#FAFAFA' },
  logo: { fontSize: 34, fontWeight: '800', color: '#0A2E5C', marginTop: 24 },
  tagline: { fontSize: 16, color: '#37474F', marginTop: 4 },
  intro: { fontSize: 14, color: '#546E7A', marginTop: 20, lineHeight: 21 },
  steps: { marginTop: 20 },
  step: {
    flexDirection: 'row',
    backgroundColor: '#FFFFFF',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#E0E0E0',
  },
  stepDone: { borderColor: '#9CCC65' },
  dot: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 2,
    borderColor: '#B0BEC5',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
    marginTop: 2,
  },
  dotDone: { backgroundColor: '#0A7B3E', borderColor: '#0A7B3E' },
  dotCheck: { color: '#FFFFFF', fontWeight: '800' },
  stepText: { flex: 1 },
  stepTitle: { fontSize: 15, fontWeight: '700', color: '#1A1A1A' },
  stepBody: { fontSize: 13, color: '#546E7A', marginTop: 3, lineHeight: 18 },
  primary: {
    backgroundColor: '#0A2E5C',
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 12,
  },
  primaryDim: { opacity: 0.6 },
  primaryText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  devSkip: { marginTop: 16, alignItems: 'center', padding: 10 },
  devSkipText: { color: '#0288D1', fontSize: 13, textDecorationLine: 'underline' },
});
