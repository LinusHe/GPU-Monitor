import torch
import time
import argparse

def load_gpu(target_load, duration, tolerance=5):
    if not torch.cuda.is_available():
        print("CUDA ist nicht verfügbar. Bitte stellen Sie sicher, dass eine CUDA-fähige GPU installiert ist.")
        return

    device = torch.device("cuda")
    
    start_time = time.time()
    end_time = start_time + duration

    while time.time() < end_time:
        # Erstelle einen großen Tensor auf der GPU
        x = torch.randn(10000, 10000, device=device)
        
        # Führe eine Matrix-Multiplikation durch
        y = torch.matmul(x, x.t())
        
        # Berechne die Summe, um sicherzustellen, dass die Operation ausgeführt wird
        z = y.sum()
        
        # Überprüfe die aktuelle GPU-Auslastung
        current_load = torch.cuda.utilization()
        
        # Passe die Wartezeit an, um die Zielauslastung zu erreichen
        if current_load < target_load - tolerance:
            time.sleep(0.01)  # Verringere die Wartezeit, um die Auslastung zu erhöhen
        elif current_load > target_load + tolerance:
            time.sleep(0.1)  # Erhöhe die Wartezeit, um die Auslastung zu verringern
        
        # Gib den aktuellen Status aus
        elapsed_time = time.time() - start_time
        print(f"Zeit: {elapsed_time:.2f}s, GPU-Auslastung: {current_load}%")

    print("GPU-Belastung abgeschlossen.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Belaste die GPU für eine bestimmte Dauer auf einen Zielbereich.")
    parser.add_argument("target_load", type=int, help="Ziel-GPU-Auslastung in Prozent")
    parser.add_argument("duration", type=int, help="Dauer der Belastung in Sekunden")
    parser.add_argument("--tolerance", type=int, default=5, help="Toleranzbereich für die Zielauslastung in Prozent")
    
    args = parser.parse_args()
    
    load_gpu(args.target_load, args.duration, args.tolerance)