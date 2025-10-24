{
  description = "A very basic flake";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
  };
  
  outputs = { self, nixpkgs }: 
  let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };

    # --- Define dependencies ---
    pythonDependencies = ps: with ps; [
      requests
      beautifulsoup4
      paho-mqtt
      python-dotenv
    ];

    # Create a Python environment with these dependencies
    pythonWithDeps = pkgs.python312.withPackages pythonDependencies;

  in
  {
    # --- Your existing devShell (unchanged) ---
    devShells.${system}.default = pkgs.mkShell
    {
      packages = with pkgs;
      [
        python312
        python312Packages.requests
        python312Packages.beautifulsoup4
        python312Packages.paho-mqtt
        python312Packages.python-dotenv
      ];
    };

    # --- Updated package section ---
    packages.${system}.default = pkgs.writeShellApplication {
      name = "enggdev-runner";
      
      runtimeInputs = [ pythonWithDeps ]; 

      text = ''
        #!/bin/sh
        # We execute the python script from the flake's root
        # "$@" passes all command-line arguments to your script.
        exec python ${self}/enggdev.py "$@"  # <-- This line is corrected
      '';
    };
  };
}