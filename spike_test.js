import http from 'k6/http';
import { check, sleep } from 'k6';

// Configuration du test de charge (Spike Test)
export const options = {
  discardResponseBodies: true, // Optimisation : on ignore le corps de la réponse pour économiser de la RAM et du CPU
  scenarios: {
    spike: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 1000 }, // 1. Montée : 1000 utilisateurs virtuels
        { duration: '30s', target: 1000 }, // 2. Maintien : 1000 requêtes simultanées 
        { duration: '10s', target: 0 },    // 3. Descente : retour au calme
      ],
      gracefulRampDown: '5s',
    },
  },
};

export default function () {
  const url = 'http://localhost/api/v1/users'; // L'API locale passe par Nginx (port 80)


  // Effectuer la requête GET (vous pouvez changer en POST si besoin)
  const res = http.get(url);

  // Vérifier si la réponse est bien 200 OK (sinon l'API est probablement tombée)
  check(res, {
    'status is 200': (r) => r.status === 200,
    // On peut aussi vérifier que l'API a répondu en moins de 2 secondes :
    // 'transaction time < 2000ms': (r) => r.timings.duration < 2000,
  });

  // Pause d'une seconde entre chaque itération d'un même utilisateur
  // Si vous enlevez ce sleep, k6 va générer une attaque DDoS pure et dure, 
  // car chaque utilisateur relancera une requête dès la fin de la précédente.
  sleep(1);
}
