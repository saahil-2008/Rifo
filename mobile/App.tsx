import AsyncStorage from '@react-native-async-storage/async-storage';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { navRef, navigateTo, RootStackParamList } from './src/navigation';
import { useVerificationFlow } from './src/useVerificationFlow';
import DetailScreen from './src/screens/DetailScreen';
import HistoryScreen from './src/screens/HistoryScreen';
import OnboardingScreen from './src/screens/OnboardingScreen';
import SettingsScreen from './src/screens/SettingsScreen';

const Stack = createNativeStackNavigator<RootStackParamList>();
const ONBOARDED_KEY = 'rifo.onboarded';

/** Rifo — four screens (FR-9) plus the app-wide overlay->verification wiring. */
export default function App(): React.JSX.Element {
  const [ready, setReady] = useState(false);
  const [onboarded, setOnboarded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(ONBOARDED_KEY)
      .then((v) => {
        setOnboarded(v === '1');
      })
      .catch(() => setOnboarded(false))
      .finally(() => setReady(true));
  }, []);

  useVerificationFlow(() => {
    Alert.alert('Overlay stopped', 'The overlay service was stopped. Re-enable it from Settings.', [
      { text: 'Open settings', onPress: () => navigateTo('Settings') },
      { text: 'OK', style: 'cancel' },
    ]);
  });

  if (!ready) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color="#0A2E5C" />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <NavigationContainer ref={navRef}>
        <Stack.Navigator
          screenOptions={{ headerShown: false, animation: 'slide_from_right' }}
          initialRouteName={onboarded ? 'History' : 'Onboarding'}>
          <Stack.Screen name="Onboarding" component={OnboardingScreen} />
          <Stack.Screen name="History" component={HistoryScreen} />
          <Stack.Screen name="Detail" component={DetailScreen} />
          <Stack.Screen name="Settings" component={SettingsScreen} />
        </Stack.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  splash: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#FAFAFA' },
});
